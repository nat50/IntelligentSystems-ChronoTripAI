"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { PlaceRow } from "@/components/app/PlaceRow";
import { CitySelect, TopBar } from "@/components/app/TopBar";
import { Button, cx, DayPicker, Slider } from "@/components/ui";
import { api } from "@/lib/api";
import { clock } from "@/lib/time";
import { MAX_PLACES, useTrip } from "@/lib/trip-store";
import type { Group, Place } from "@/lib/types";
import s from "../screen.module.css";

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

const FILTERS: { key: Group | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "sightseeing", label: "Sights" },
  { key: "food", label: "Food" },
  { key: "entertainment", label: "Fun" },
  { key: "shopping", label: "Shopping" },
  { key: "nightlife", label: "Night" },
];

const SLOTS = Array.from({ length: 39 }, (_, i) => 5 * 60 + i * 30); // 05:00 … 24:00

const paceLabel = (v: number) => (v < 0.34 ? "Relaxed" : v > 0.66 ? "Packed" : "Balanced");

export function PlacesScreen() {
  const router = useRouter();
  const { state, dispatch, cities, optimize, optimizing, error, clearError, hydrated } = useTrip();
  const [inView, setInView] = useState<Place[]>([]);
  const [bbox, setBbox] = useState<string | null>(null);
  const [filter, setFilter] = useState<Group | "all">("all");
  const [hovered, setHovered] = useState<number | null>(null);
  const [more, setMore] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const city = cities.find((c) => c.name === state.city);
  const selectedIds = useMemo(() => new Set(state.selected.map((p) => p.id)), [state.selected]);

  // candidates inside the visible map area (debounced)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    if (!bbox) return;
    clearTimeout(timer.current);
    let alive = true;
    timer.current = setTimeout(() => {
      api
        .places(state.city, { bbox, limit: 400 })
        .then((list) => {
          if (!alive) return;
          setInView(list);
          setLoadError(null);
        })
        .catch((e: Error) => alive && setLoadError(e.message));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer.current);
    };
  }, [bbox, state.city]);

  const mapPlaces = useMemo(() => {
    const ids = new Set(inView.map((p) => p.id));
    return [...inView, ...state.selected.filter((p) => !ids.has(p.id))];
  }, [inView, state.selected]);

  const candidates = useMemo(
    () => inView.filter((p) => !selectedIds.has(p.id) && (filter === "all" || p.group === filter)),
    [inView, selectedIds, filter],
  );

  const suggest = async () => {
    setSuggesting(true);
    try {
      dispatch({ type: "add", places: await api.suggest(state.city, 8) });
    } catch (e) {
      setLoadError((e as Error).message);
    } finally {
      setSuggesting(false);
    }
  };

  const build = async () => {
    const it = await optimize({ seed: false });
    if (it) router.push("/plan/itinerary");
  };

  const short = state.city === "Ho Chi Minh City" ? "HCMC" : state.city;
  const full = state.selected.length >= MAX_PLACES;

  return (
    <div className={s.screen}>
      <TopBar
        items={[
          { href: "/plan", label: "Places" },
          { href: "/plan/itinerary", label: "Itinerary", disabled: !state.itinerary },
        ]}
        active="/plan"
        right={
          <CitySelect value={state.city} options={cities.map((c) => c.name)} onChange={(c) => dispatch({ type: "city", city: c })} />
        }
      />
      <div className={s.body}>
        <aside className={s.panel}>
          <div>
            <h1 className={s.h1}>Pick places</h1>
            <p className={s.sub}>
              {short} · <span className={s.count}>{state.selected.length}</span> of {MAX_PLACES} selected
            </p>
          </div>

          <section className={s.trip} aria-label="Trip settings">
            <div className={s.row}>
              <span>Days</span>
              <DayPicker value={state.days - 1} onChange={(d) => dispatch({ type: "days", days: d + 1 })} />
            </div>
            <div className={s.row}>
              <span>Each day</span>
              <span className={s.hours}>
                <select
                  className={s.timeInput}
                  aria-label="Day starts"
                  value={state.dayStart}
                  onChange={(e) => dispatch({ type: "hours", dayStart: Number(e.target.value), dayEnd: Math.max(state.dayEnd, Number(e.target.value) + 120) })}
                >
                  {SLOTS.filter((m) => m <= 20 * 60).map((m) => (
                    <option key={m} value={m}>
                      {clock(m)}
                    </option>
                  ))}
                </select>
                –
                <select
                  className={s.timeInput}
                  aria-label="Day ends"
                  value={state.dayEnd}
                  onChange={(e) => dispatch({ type: "hours", dayStart: state.dayStart, dayEnd: Number(e.target.value) })}
                >
                  {SLOTS.filter((m) => m >= state.dayStart + 120).map((m) => (
                    <option key={m} value={m}>
                      {clock(m)}
                    </option>
                  ))}
                </select>
              </span>
            </div>
            <div className={s.sliderBlock}>
              <div className={s.row}>
                <span>Pace</span>
                <span className={s.rowValue}>{paceLabel(state.prefs.pace)}</span>
              </div>
              <Slider label="Pace" value={state.prefs.pace} onChange={(v) => dispatch({ type: "prefs", prefs: { pace: v } })} />
            </div>
            {more && (
              <>
                <div className={s.sliderBlock}>
                  <div className={s.row}>
                    <span>Travel</span>
                  </div>
                  <Slider label="Travel" value={state.prefs.travel} onChange={(v) => dispatch({ type: "prefs", prefs: { travel: v } })} />
                  <div className={s.scale}>
                    <span>Go anywhere</span>
                    <span>Keep it close</span>
                  </div>
                </div>
                <div className={s.sliderBlock}>
                  <div className={s.row}>
                    <span>Hours &amp; meals</span>
                  </div>
                  <Slider
                    label="Opening hours and meals"
                    value={state.prefs.strictness}
                    onChange={(v) => dispatch({ type: "prefs", prefs: { strictness: v } })}
                  />
                  <div className={s.scale}>
                    <span>Flexible</span>
                    <span>Strict</span>
                  </div>
                </div>
              </>
            )}
            <button type="button" className={s.more} onClick={() => setMore((m) => !m)} aria-expanded={more}>
              {more ? "Fewer preferences" : "More preferences"}
            </button>
          </section>

          <div className={s.toolbar}>
            {FILTERS.map((f) => (
              <button key={f.key} type="button" className={cx(s.chip, filter === f.key && s.chipOn)} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
            <span className={s.toolbarEnd}>
              <Button variant="ghost" onClick={suggest} loading={suggesting} disabled={full}>
                ✦ Suggest
              </Button>
            </span>
          </div>

          <div className={s.list} data-lenis-prevent>
            {state.selected.length > 0 && <p className={s.listLabel}>Your places</p>}
            {state.selected.map((p) => (
              <PlaceRow
                key={p.id}
                place={p}
                selected
                hovered={hovered === p.id}
                onToggle={() => dispatch({ type: "toggle", place: p })}
                onHover={setHovered}
              />
            ))}
            <p className={s.listLabel}>On the map · by score</p>
            {candidates.slice(0, 60).map((p) => (
              <PlaceRow
                key={p.id}
                place={p}
                selected={false}
                hovered={hovered === p.id}
                onToggle={() => dispatch({ type: "toggle", place: p })}
                onHover={setHovered}
              />
            ))}
            {hydrated && candidates.length === 0 && (
              <p className={s.empty}>{loadError ?? "No places here — move or zoom the map."}</p>
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
            {full && <p className={s.meta}>That&apos;s the maximum of {MAX_PLACES} places for one trip.</p>}
            <Button block onClick={build} loading={optimizing} disabled={state.selected.length === 0 || !state.stay}>
              {optimizing ? "Optimizing…" : "Build itinerary"}
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
              onPlaceClick={(p) => dispatch({ type: "toggle", place: p })}
              stay={state.stay}
              onStayChange={(stay) => dispatch({ type: "stay", stay })}
              onBoundsChange={setBbox}
            />
          )}
        </div>
      </div>
    </div>
  );
}
