"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AccountMenu } from "@/components/app/Account";
import { TopBar } from "@/components/app/TopBar";
import { Button, cx, Pill, Toggle, type Tone } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { loadTripRefs, type TripRef } from "@/lib/saved-trips";
import { clock, dateRange, duration, fmtDate, tripDate } from "@/lib/time";
import { useTrip } from "@/lib/trip-store";
import type { DayOverview, Trip, TripStatus } from "@/lib/types";
import { dayTitle } from "../itinerary/ItineraryScreen";
import s from "./trips.module.css";

const STATUS: Record<TripStatus, [Tone, string]> = {
  upcoming: ["ok", "Upcoming"],
  draft: ["warn", "Draft"],
  past: ["neutral", "Past"],
};

export const tripMeta = (t: { start_date: string | null; end_date: string | null; days: number }, stops: number) =>
  `${dateRange(t.start_date, t.end_date)} · ${t.days} ${t.days === 1 ? "day" : "days"} · ${stops} stops`;

/** Card preview: the trip's stops as dots, scaled into the box */
function MiniMap({ trip, on }: { trip: Trip; on: boolean }) {
  const pts = trip.itinerary?.days.flatMap((d) => d.stops.map((x) => [x.place.lon, x.place.lat])) ?? [];
  if (pts.length === 0) pts.push([trip.request.stay.lon, trip.request.stay.lat]);
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => 30 + (240 * (x - x0)) / (x1 - x0 || 1);
  const sy = (y: number) => 110 - (80 * (y - y0)) / (y1 - y0 || 1);
  return (
    <svg className={s.mini} viewBox="0 0 300 140" aria-hidden>
      {pts.slice(0, 40).map(([x, y], i) => (
        <circle key={i} cx={pts.length > 1 ? sx(x) : 150} cy={pts.length > 1 ? sy(y) : 70} r="6" fill={on ? "var(--accent)" : "var(--pin-idle)"} />
      ))}
    </svg>
  );
}

export function OverviewTable({ title, rows, start }: { title: string; rows: DayOverview[]; start: string | null }) {
  return (
    <section className={s.overview}>
      <h2 className={s.h3}>{title} · day overview</h2>
      <table className={s.table}>
        <thead>
          <tr>
            <th>Day</th>
            <th>Stops</th>
            <th>Travel</th>
            <th>First stop</th>
            <th>Back at hotel</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.day}>
              <td>
                Day {d.day + 1}
                {start ? ` · ${fmtDate(tripDate(start, d.day), { weekday: "short" })}` : ""}
              </td>
              <td>{d.stops}</td>
              <td>{duration(d.travel_minutes)}</td>
              <td>{d.first_stop != null ? clock(d.first_stop) : "—"}</td>
              <td>{clock(d.back_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/** "PDF itinerary": printed through the browser, one page per day */
function PrintView({ trip }: { trip: Trip }) {
  return createPortal(
    <div data-print className={s.print}>
      <h1>
        {trip.city} · {dateRange(trip.start_date, trip.end_date)}
      </h1>
      {trip.itinerary?.days.map((d) => (
        <section key={d.day} className={s.printDay}>
          <h2>{dayTitle(trip.start_date, d.day)}</h2>
          <p>
            {d.stops.length} stops · {duration(d.travel_minutes)} travel · back at {clock(d.return_time)}
          </p>
          <table>
            <tbody>
              {d.stops.map((x) => (
                <tr key={x.place.id}>
                  <td>
                    {clock(x.start)}–{clock(x.depart)}
                  </td>
                  <td>
                    {x.place.label} · {x.place.ward}
                  </td>
                  <td>{x.travel_in ? `${x.travel_in} min by car before` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      <p className={s.printNote}>Opening hours, best times and visit lengths are estimates from check-in data (ChronoTrip AI).</p>
    </div>,
    document.body,
  );
}

function ExportRow({ title, text, href, disabled, onClick }: { title: string; text: string; href?: string; disabled?: string; onClick?: () => void }) {
  return (
    <div className={s.exportRow}>
      <span>
        <strong>{title}</strong>
        <span>{disabled ?? text}</span>
      </span>
      {href && !disabled ? (
        <a className={s.download} href={href} download>
          Download
        </a>
      ) : (
        <Button variant="outline" onClick={onClick} disabled={Boolean(disabled)}>
          Download
        </Button>
      )}
    </div>
  );
}

export function TripsScreen() {
  const router = useRouter();
  const { state, dispatch, openTrip } = useTrip();
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [refs, setRefs] = useState<TripRef[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const list = loadTripRefs();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time read of localStorage
    setRefs(list);
    if (list.length === 0) {
      setTrips([]);
      return;
    }
    const want = Number(new URLSearchParams(window.location.search).get("id"));
    api
      .lookupTrips(list)
      .then((found) => {
        setTrips(found);
        setSelected(found.find((t) => t.id === want)?.id ?? found[0]?.id ?? null);
      })
      .catch((e: Error) => {
        setTrips([]);
        setError(e.message);
      });
  }, []);

  const trip = trips?.find((t) => t.id === selected) ?? null;
  const ref = refs.find((r) => r.id === selected);
  const replace = (t: Trip) => setTrips((list) => list?.map((x) => (x.id === t.id ? t : x)) ?? null);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
    } finally {
      setBusy(null);
    }
  };

  const open = (t: Trip) =>
    run(`open:${t.id}`, async () => {
      const r = refs.find((x) => x.id === t.id);
      if (!r) return;
      await openTrip(t, r);
      router.push(t.itinerary && !t.stale_places.length ? "/plan/itinerary" : "/plan/places");
    });

  const share = (on: boolean) =>
    trip && ref && run("share", async () => replace(await api.shareTrip(trip.id, ref.token, on)));

  const improve = (on: boolean) =>
    trip &&
    ref &&
    run("improve", async () => {
      replace(await api.updateTrip(trip.id, ref.token, { improve_estimates: on }));
      // edits made on this trip before agreeing are sent now
      if (on && state.tripRef?.id === trip.id && state.edits.length) {
        await api.sendEdits(trip.id, ref.token, state.edits);
        dispatch({ type: "saved", ref });
      }
    });

  const link = trip?.share_slug ? `${window.location.origin}/t/${trip.share_slug}` : "";

  return (
    <div className={s.page}>
      <TopBar
        items={[
          { href: "/plan", label: "Plan a trip" },
          { href: "/plan/trips", label: "Saved trips" },
        ]}
        active="/plan/trips"
        right={<AccountMenu />}
      />
      <div className={s.body}>
        <main className={s.main}>
          <div className={s.head}>
            <div>
              <h1 className={s.h1}>Saved trips</h1>
              <p className={s.sub}>{trips ? `${trips.length} ${trips.length === 1 ? "trip" : "trips"} · sorted by start date` : "Loading…"}</p>
            </div>
            <Button
              onClick={() => {
                dispatch({ type: "reset" });
                router.push("/plan");
              }}
            >
              New trip
            </Button>
          </div>
          {error && (
            <p className={s.error} role="alert">
              {error}
            </p>
          )}

          {trips?.length === 0 && (
            <div className={s.empty}>
              <h2 className={s.h3}>No saved trips yet</h2>
              <p>Build an itinerary and press “Save trip”. Trips are kept in this browser, no account needed.</p>
            </div>
          )}

          <div className={s.cards}>
            {trips?.map((t) => {
              const [tone, label] = STATUS[t.status];
              const on = t.id === selected;
              return (
                <article
                  key={t.id}
                  className={cx(s.card, on && s.cardOn)}
                  tabIndex={0}
                  aria-current={on || undefined}
                  aria-label={`${t.city}, ${tripMeta(t, t.stops)}`}
                  onClick={() => setSelected(t.id)}
                  onKeyDown={(e) => e.key === "Enter" && e.target === e.currentTarget && setSelected(t.id)}
                >
                  <MiniMap trip={t} on={on} />
                  <div className={s.cardBody}>
                    <Pill small tone={tone}>
                      {label}
                    </Pill>
                    <h2 className={s.cardTitle}>{t.city}</h2>
                    <p className={s.sub}>{tripMeta(t, t.stops)}</p>
                    {t.stale_places.length > 0 && (
                      <p className={s.stale}>
                        {t.stale_places.length} {t.stale_places.length === 1 ? "place is" : "places are"} no longer in the data · plan again
                      </p>
                    )}
                    <Button
                      variant="outline"
                      loading={busy === `open:${t.id}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        void open(t);
                      }}
                    >
                      Open
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>

          {trip && trip.overview.length > 0 && <OverviewTable title={trip.city} rows={trip.overview} start={trip.start_date} />}
        </main>

        {trip && ref && (
          <aside className={s.side}>
            <div>
              <h2 className={s.h2}>Share and export</h2>
              <p className={s.sub}>
                {trip.city} · {dateRange(trip.start_date, trip.end_date)}
              </p>
            </div>

            <div className={s.box}>
              <div className={s.boxRow}>
                <span>
                  <strong>Share with a link</strong>
                  <span>Anyone with the link can view, not edit.</span>
                </span>
                <Toggle label="Share with a link" checked={trip.share_enabled} disabled={busy === "share"} onChange={share} />
              </div>
              {trip.share_enabled && link && (
                <div className={s.link}>
                  <span title={link}>{link.replace(/^https?:\/\//, "")}</span>
                  <button
                    type="button"
                    onClick={() =>
                      navigator.clipboard.writeText(link).then(() => {
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      })
                    }
                  >
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
              )}
            </div>

            <div className={s.exports}>
              <span className={s.label}>Export</span>
              <ExportRow title="PDF itinerary" text="Print-ready, one page per day" disabled={trip.itinerary ? undefined : "Build the itinerary first"} onClick={() => window.print()} />
              <ExportRow
                title="Calendar file (.ics)"
                text="Adds each stop as an event"
                href={api.exportUrl(trip.id, ref.token, "ics")}
                disabled={!trip.itinerary ? "Build the itinerary first" : !trip.start_date ? "Set a start date to add events" : undefined}
              />
              <ExportRow
                title="Route file (.gpx)"
                text="Opens in map apps"
                href={api.exportUrl(trip.id, ref.token, "gpx")}
                disabled={trip.itinerary ? undefined : "Build the itinerary first"}
              />
            </div>

            <div className={cx(s.box, s.boxBlue)}>
              <div className={s.boxRow}>
                <span>
                  <strong>Help improve estimates</strong>
                  <span>Send my edits anonymously so the data team can retrain visit-length estimates.</span>
                </span>
                <Toggle label="Help improve estimates" checked={trip.improve_estimates} disabled={busy === "improve"} onChange={improve} />
              </div>
            </div>
          </aside>
        )}
      </div>
      {trip?.itinerary && <PrintView trip={trip} />}
    </div>
  );
}
