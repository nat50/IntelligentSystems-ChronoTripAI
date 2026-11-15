"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { Between, StopLine } from "@/components/app/StopRow";
import { TopBar } from "@/components/app/TopBar";
import { cx } from "@/components/ui";
import type { RouteDay } from "@/components/map/MapView";
import { api } from "@/lib/api";
import { clock, dateRange } from "@/lib/time";
import type { SharedTrip } from "@/lib/types";
import { dayTitle } from "../itinerary/ItineraryScreen";
import scr from "../screen.module.css";
import { tripMeta } from "./TripsScreen";
import s from "./trips.module.css";

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });
const ROUTE_COLORS = ["#d6336c", "#1a73e8", "#188038"];

/** Read-only trip behind a share link: /t/<slug> */
export function SharedScreen({ slug }: { slug: string }) {
  const [trip, setTrip] = useState<SharedTrip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    api
      .shared(slug)
      .then(setTrip)
      .catch(() => setError("This link does not exist or sharing was turned off."));
  }, [slug]);

  const it = trip?.itinerary;
  const routes: RouteDay[] | undefined = useMemo(
    () => it?.days.map((d) => ({ day: d.day, color: ROUTE_COLORS[d.day], stops: d.stops.map((x) => ({ place: x.place, start: x.start })) })),
    [it],
  );
  const first = it?.days.find((d) => d.stops.length)?.stops[0]?.place;
  const day = it?.days[active];

  return (
    <div className={scr.screen}>
      <TopBar items={[]} active="" right={<Link href="/plan" className={scr.editLink}>Plan your own trip</Link>} />
      {!trip ? (
        <div className={scr.emptyState}>
          <p>{error ?? "Loading the trip…"}</p>
        </div>
      ) : (
        <div className={scr.body}>
          <aside className={cx(scr.panel, scr.panelWide)}>
            <div>
              <h1 className={scr.h1}>{trip.city}</h1>
              <p className={scr.sub}>{tripMeta(trip, it?.days.reduce((n, d) => n + d.stops.length, 0) ?? 0)}</p>
            </div>
            {it && day ? (
              <>
                <div className={scr.head}>
                  <h2 className={s.h3}>{dayTitle(trip.start_date, day.day)}</h2>
                  <div className={scr.dayTabs} role="tablist" aria-label="Day">
                    {it.days.map((d) => (
                      <button key={d.day} type="button" role="tab" aria-selected={d.day === active} className={cx(scr.dayTab, d.day === active && scr.dayTabOn)} onClick={() => setActive(d.day)}>
                        Day {d.day + 1}
                      </button>
                    ))}
                  </div>
                </div>
                <p className={scr.summary}>
                  {day.stops.length} stops · {day.travel_minutes} min travel · back at {clock(day.return_time)}
                </p>
                <div className={scr.stops}>
                  {day.stops.map((x, i) => (
                    <Fragment key={x.place.id}>
                      {i > 0 && <Between travel={x.travel_in} meal={x.meal_break_before} />}
                      <StopLine stop={x} day={day.day} />
                    </Fragment>
                  ))}
                </div>
                <div className={scr.actions2}>
                  <a className={s.download} href={api.sharedExportUrl(slug, "gpx")} download>
                    Route (.gpx)
                  </a>
                  {trip.start_date && (
                    <a className={s.download} href={api.sharedExportUrl(slug, "ics")} download>
                      Calendar (.ics)
                    </a>
                  )}
                </div>
                <p className={scr.meta}>{dateRange(trip.start_date, trip.end_date)} · times and opening hours are estimates</p>
              </>
            ) : (
              <p className={scr.empty}>This trip has no schedule yet.</p>
            )}
          </aside>
          <div className={scr.mapArea}>
            {first && <MapView center={{ lat: first.lat, lon: first.lon }} routes={routes} activeDay={active} fitKey={`${slug}-${active}`} />}
          </div>
        </div>
      )}
    </div>
  );
}
