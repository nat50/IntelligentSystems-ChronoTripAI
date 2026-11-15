"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { PlaceRow } from "@/components/app/PlaceRow";
import { TopBar } from "@/components/app/TopBar";
import { Button, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { duration } from "@/lib/time";
import { INTERESTS, MAX_PLACES, useTrip } from "@/lib/trip-store";
import type { Interest, Place } from "@/lib/types";
import { planNav, TripSummary } from "../plan-nav";
import s from "../screen.module.css";
import { PlaceDetailPanel } from "./PlaceDetailPanel";

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

const matches = (p: Place, filter: Interest | "all", text: string) =>
  (filter === "all" || !p.interest || p.interest === filter) &&
  (!text || `${p.label} ${p.ward} ${p.category}`.toLowerCase().includes(text));

export function PlacesScreen() {
  const router = useRouter();
  const { state, dispatch, cities, optimize, error, clearError, hydrated } = useTrip();
  const [found, setFound] = useState<Place[]>([]);
  const [bbox, setBbox] = useState<string | null>(null);
  const [filter, setFilter] = useState<Interest | "all">("all");
  const [query, setQuery] = useState("");
  const [hovered, setHovered] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const city = cities.find((c) => c.name === state.city);
  const selectedIds = useMemo(() => new Set(state.selected.map((p) => p.id)), [state.selected]);
  const mustIds = useMemo(() => new Set(state.mustVisit), [state.mustVisit]);
  const text = query.trim().toLowerCase();

  // D2 "Open in traveler view" links here with ?place=<id>
  useEffect(() => {
    if (!hydrated) return;
    const id = Number(new URLSearchParams(window.location.search).get("place"));
    if (!id) return;
    api
      .place(id)
      .then((p) => {
        if (p.city !== state.city) dispatch({ type: "city", city: p.city });
        setOpenId(p.id);
      })
      .catch(() => {});
    // once, after the trip is restored
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated]);

  // candidates: search text over the whole city, otherwise the visible map area
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    if (!bbox && !text) return;
    clearTimeout(timer.current);
    let alive = true;
    const interest = filter === "all" ? undefined : [filter];
    timer.current = setTimeout(() => {
      api
        .places(state.city, text ? { q: text, interest, limit: 60 } : { bbox: bbox!, interest, limit: 400 })
        .then((list) => {
          if (!alive) return;
          setFound(list);
          setLoadError(null);
        })
        .catch((e: Error) => alive && setLoadError(e.message));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer.current);
    };
  }, [bbox, text, filter, state.city]);

  const mapPlaces = useMemo(() => {
    const ids = new Set(found.map((p) => p.id));
    return [...found, ...state.selected.filter((p) => !ids.has(p.id))];
  }, [found, state.selected]);

  const yours = state.selected.filter((p) => matches(p, filter, text));
  const candidates = found.filter((p) => !selectedIds.has(p.id)).slice(0, 60);

  const suggest = async () => {
    setSuggesting(true);
    try {
      dispatch({ type: "add", places: await api.suggest(state.city, 8, state.interests.length ? state.interests : undefined) });
    } catch (e) {
      setLoadError((e as Error).message);
    } finally {
      setSuggesting(false);
    }
  };

  const build = () => {
    void optimize({ seed: false });
    router.push("/plan/itinerary");
  };

  const full = state.selected.length >= MAX_PLACES;
  const visit = state.selected.reduce((sum, p) => sum + p.duration, 0);
  const perDay = state.dayEnd - state.dayStart;
  const available = perDay * state.days;
  const share = Math.min(1, visit / Math.max(available, 1));

  return (
    <div className={s.screen}>
      <TopBar items={planNav(state, "/plan/places")} active="/plan/places" right={<TripSummary state={state} />} />
      <div className={s.body}>
        <aside className={s.panel}>
          <div>
            <h1 className={s.h1}>Pick places</h1>
            <p className={s.sub}>
              <span className={s.count}>{state.selected.length}</span> selected for {state.days} {state.days === 1 ? "day" : "days"} ·{" "}
              {MAX_PLACES} places max · sorted by popularity
            </p>
          </div>

          <label className={s.search}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              type="search"
              placeholder="Search places or areas"
              aria-label="Search places or areas"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>

          <div className={s.toolbar}>
            {[{ key: "all" as const, label: "All" }, ...INTERESTS].map((f) => (
              <button key={f.key} type="button" aria-pressed={filter === f.key} className={cx(s.chip, filter === f.key && s.chipOn)} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
            <Button variant="ghost" onClick={suggest} loading={suggesting} disabled={full} className={s.toolbarEnd}>
              ✦ Suggest
            </Button>
          </div>

          <div className={s.list} data-lenis-prevent>
            {yours.map((p) => (
              <PlaceRow
                key={p.id}
                place={p}
                selected
                must={mustIds.has(p.id)}
                active={openId === p.id}
                hovered={hovered === p.id}
                onToggle={() => dispatch({ type: "toggle", place: p })}
                onOpen={() => setOpenId(p.id)}
                onHover={setHovered}
              />
            ))}
            {candidates.length > 0 && <p className={s.listLabel}>{text ? "Search results" : "On the map · by popularity"}</p>}
            {candidates.map((p) => (
              <PlaceRow
                key={p.id}
                place={p}
                selected={false}
                active={openId === p.id}
                hovered={hovered === p.id}
                onToggle={() => dispatch({ type: "toggle", place: p })}
                onOpen={() => setOpenId(p.id)}
                onHover={setHovered}
              />
            ))}
            {hydrated && yours.length + candidates.length === 0 && (
              <p className={s.empty}>{loadError ?? (text ? "No place matches your search." : "No places here — move or zoom the map.")}</p>
            )}
          </div>

          <div className={s.footer}>
            {error && (
              <div className={s.error} role="alert">
                {error}
                <button className={s.errorClose} onClick={clearError} aria-label="Dismiss">
                  ×
                </button>
              </div>
            )}
            <div className={s.budget}>
              <span>Visit time of selected</span>
              <strong>{duration(visit)}</strong>
              <span>
                Available ({state.days} × {duration(perDay)})
              </span>
              <strong>{duration(available)}</strong>
              <span className={s.budgetBar} role="progressbar" aria-label="Share of available time" aria-valuenow={Math.round(share * 100)} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${share * 100}%` }} data-over={visit > available || undefined} />
              </span>
            </div>
            {full && <p className={s.meta}>That&apos;s the maximum of {MAX_PLACES} places for one trip.</p>}
            <Button block onClick={build} disabled={state.selected.length === 0 || !state.stay}>
              Build itinerary
            </Button>
          </div>
        </aside>

        <div className={s.mapArea}>
          {city && (
            <MapView
              center={{ lat: city.lat, lon: city.lon }}
              places={mapPlaces}
              selectedIds={selectedIds}
              hoveredId={hovered}
              onHover={setHovered}
              onPlaceClick={(p) => setOpenId(p.id)}
              stay={state.stay}
              onStayChange={(stay) => dispatch({ type: "stay", stay: { ...stay, label: state.stay?.label ?? stay.label } })}
              onBoundsChange={setBbox}
            />
          )}
          <div className={s.legend} aria-hidden>
            <span>
              <i className={s.dotSelected} /> Selected
            </span>
            <span>
              <i className={s.dotIdle} /> Not selected
            </span>
            <span>
              <i className={s.dotStay} /> Stay (H)
            </span>
          </div>
        </div>

        {openId != null && (
          <PlaceDetailPanel
            id={openId}
            selected={selectedIds.has(openId)}
            must={mustIds.has(openId)}
            full={full}
            onToggle={(p) => dispatch({ type: "toggle", place: p })}
            onMust={(p, on) => dispatch({ type: "mustVisit", place: p, on })}
            onClose={() => setOpenId(null)}
          />
        )}
      </div>
    </div>
  );
}
