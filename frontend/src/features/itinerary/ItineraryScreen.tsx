"use client";

import {
  closestCenter,
  DndContext,
  type DragEndEvent,
  type DragOverEvent,
  KeyboardSensor,
  PointerSensor,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import dynamic from "next/dynamic";
import { Fragment, useMemo, useState, type CSSProperties } from "react";
import { Between, StopRow } from "@/components/app/StopRow";
import { TopBar } from "@/components/app/TopBar";
import { Button, ButtonLink, cx, DAY_COLORS } from "@/components/ui";
import ui from "@/components/ui/ui.module.css";
import { clock } from "@/lib/time";
import { useTrip } from "@/lib/trip-store";
import type { Lock } from "@/lib/types";
import type { RouteDay } from "@/components/map/MapView";
import s from "../screen.module.css";

const ROUTE_COLORS = ["#d6336c", "#1a73e8", "#188038"]; // --day-1..3 (MapLibre needs literal colours)

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

function DayTab({ day, active, over, onClick }: { day: number; active: boolean; over: boolean; onClick: () => void }) {
  const { setNodeRef } = useDroppable({ id: `day-${day}` });
  return (
    <button
      ref={setNodeRef}
      type="button"
      role="tab"
      aria-selected={active}
      className={cx(ui.day, active && ui.dayActive, over && ui.dayDrop)}
      style={{ "--day-color": DAY_COLORS[day] } as CSSProperties}
      onClick={onClick}
      title={`Day ${day + 1} — drop a stop here to move it`}
    >
      {day + 1}
    </button>
  );
}

export function ItineraryScreen() {
  const { state, dispatch, cities, optimize, optimizing, error, clearError, hydrated } = useTrip();
  const [hovered, setHovered] = useState<number | null>(null);
  const [overDay, setOverDay] = useState<number | null>(null);
  const it = state.itinerary;
  const city = cities.find((c) => c.name === state.city);
  const lockedIds = useMemo(() => new Map(state.locks.map((l) => [l.place_id, l])), [state.locks]);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const routes: RouteDay[] | undefined = useMemo(
    () =>
      it?.days.map((d) => ({
        day: d.day,
        color: ROUTE_COLORS[d.day],
        stops: d.stops.map((x) => ({ place: x.place, start: x.start })),
      })),
    [it],
  );

  const top = (
    <TopBar
      items={[
        { href: "/plan", label: "Places" },
        { href: "/plan/itinerary", label: "Itinerary" },
      ]}
      active="/plan/itinerary"
      right={<span>{state.city}</span>}
    />
  );

  if (!hydrated) return <div className={s.screen}>{top}</div>;
  if (!it) {
    return (
      <div className={s.screen}>
        {top}
        <div className={s.emptyState}>
          <div>
            <h1 className={s.h1}>No itinerary yet</h1>
            <p>Pick a few places first — ChronoTrip will put them in the right order.</p>
            <ButtonLink href="/plan">Pick places</ButtonLink>
          </div>
        </div>
      </div>
    );
  }

  const day = it.days[Math.min(state.activeDay, it.days.length - 1)];
  const stops = day.stops;

  const reoptimize = (locks?: Lock[]) => optimize({ locks, seed: true });

  const toggleLock = (placeId: number, start: number) => {
    if (lockedIds.has(placeId)) dispatch({ type: "unlock", placeId });
    else dispatch({ type: "lock", lock: { place_id: placeId, day: day.day, start } });
  };

  const onDragOver = (e: DragOverEvent) => {
    const id = String(e.over?.id ?? "");
    setOverDay(id.startsWith("day-") ? Number(id.slice(4)) : null);
  };

  // FR-05: dropping pins the moved stop (day + time slot) and re-optimises the rest
  const onDragEnd = (e: DragEndEvent) => {
    setOverDay(null);
    const placeId = Number(e.active.id);
    const overId = String(e.over?.id ?? "");
    if (!overId || overId === String(placeId)) return;
    let lock: Lock;
    if (overId.startsWith("day-")) {
      const target = Number(overId.slice(4));
      if (target === day.day) return;
      lock = { place_id: placeId, day: target, start: null };
      dispatch({ type: "activeDay", day: target });
    } else {
      const slot = stops.find((x) => x.place.id === Number(overId));
      if (!slot) return;
      lock = { place_id: placeId, day: day.day, start: slot.start };
    }
    const locks = [...state.locks.filter((l) => l.place_id !== placeId), lock];
    dispatch({ type: "lock", lock });
    void reoptimize(locks);
  };

  return (
    <div className={s.screen}>
      {top}
      <div className={s.body}>
        <aside className={cx(s.panel, s.panelWide)}>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragOver={onDragOver} onDragEnd={onDragEnd} onDragCancel={() => setOverDay(null)}>
            <div className={s.head}>
              <h1 className={s.h1}>Day {day.day + 1}</h1>
              <div className={ui.days} role="tablist" aria-label="Day">
                {it.days.map((d) => (
                  <DayTab
                    key={d.day}
                    day={d.day}
                    active={d.day === day.day}
                    over={overDay === d.day}
                    onClick={() => dispatch({ type: "activeDay", day: d.day })}
                  />
                ))}
              </div>
            </div>
            <p className={s.summary}>
              {stops.length} stops · {day.travel_minutes} min travel · back by {clock(day.return_time)}
            </p>
            {day.warnings.length > 0 && (
              <div className={s.warnings} role="status">
                {day.warnings.map((w) => (
                  <span key={w}>⚠ {w}</span>
                ))}
              </div>
            )}

            <div className={s.stops} data-lenis-prevent>
              <SortableContext items={stops.map((x) => x.place.id)} strategy={verticalListSortingStrategy}>
                {stops.map((x, i) => (
                  <Fragment key={x.place.id}>
                    {i > 0 && <Between travel={x.travel_in} meal={x.meal_break_before} />}
                    <StopRow
                      stop={{ ...x, locked: lockedIds.has(x.place.id), locked_start: lockedIds.get(x.place.id)?.start ?? null }}
                      day={day.day}
                      last={false}
                      onLockToggle={() => toggleLock(x.place.id, x.start)}
                      onHover={setHovered}
                    />
                  </Fragment>
                ))}
              </SortableContext>
              {day.meal_break_before_return > 0 && <Between travel={0} meal={day.meal_break_before_return} />}
              <div className={s.returnRow}>
                <span className={s.returnTime}>{clock(day.return_time)}</span>
                <span className={s.returnDot} aria-hidden />
                <span>Back at your stay · {day.return_travel} min ride</span>
              </div>
              {stops.length === 0 && <p className={s.empty}>Nothing fits this day yet. Add places or extend the hours.</p>}
            </div>
          </DndContext>

          {error && (
            <div className={s.error} role="alert">
              {error}
              <button className={s.errorClose} onClick={clearError} aria-label="Dismiss">
                ×
              </button>
            </div>
          )}
          {it.unscheduled.length > 0 && (
            <div className={s.notScheduled}>
              <span className={s.notScheduledTitle}>Not scheduled</span>
              <span className={s.notScheduledList}>
                {it.unscheduled.map((p) => `${p.label} · ${p.ward}`).join(", ")}
              </span>
            </div>
          )}
          <p className={s.meta}>
            Memetic GA · {it.generations} generations in {it.runtime_s}s · travel times{" "}
            {it.travel_source === "osrm" ? "from OSRM (no live traffic)" : "estimated from distance"} · all place
            attributes are estimates
          </p>
        </aside>

        <div className={s.mapArea}>
          <Button className={s.mapButton} onClick={() => reoptimize()} loading={optimizing}>
            Re-optimize
          </Button>
          {optimizing && (
            <div className={s.busy}>
              <div className={s.busyCard}>
                <span className={s.dna} aria-hidden>
                  <span />
                  <span />
                  <span />
                  <span />
                </span>
                Evolving a better day…
              </div>
            </div>
          )}
          {city && (
            <MapView
              center={{ lat: city.lat, lon: city.lon }}
              hoveredId={hovered}
              onHover={setHovered}
              stay={state.stay}
              routes={routes}
              activeDay={day.day}
              fitKey={`${it.fitness}-${it.days.length}`}
            />
          )}
        </div>
      </div>
    </div>
  );
}
