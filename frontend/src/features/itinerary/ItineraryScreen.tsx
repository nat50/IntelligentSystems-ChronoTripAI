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
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { Fragment, useMemo, useState } from "react";
import { Between, StopRow } from "@/components/app/StopRow";
import { TopBar } from "@/components/app/TopBar";
import { Button, ButtonLink, cx, Modal, Pill } from "@/components/ui";
import type { RouteDay } from "@/components/map/MapView";
import { clock, duration, fmtDate, tripDate } from "@/lib/time";
import { useTrip, type TripState } from "@/lib/trip-store";
import type { Day, Itinerary, Lock, OptimizeJob, OptimizeRequest, PlanFit, PlanFix, Stop } from "@/lib/types";
import { planNav, TripSummary } from "../plan-nav";
import s from "../screen.module.css";

const ROUTE_COLORS = ["#d6336c", "#1a73e8", "#188038"]; // --day-1..3 (MapLibre needs literal colours)

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

export const dayTitle = (start: string | null, day: number) =>
  start ? fmtDate(tripDate(start, day), { weekday: "short", day: "numeric", month: "short" }) : `Day ${day + 1}`;

/** Largest free time left in any day: what an unscheduled place would need to fit */
function largestGap(it: Itinerary, dayEnd: number): number {
  let best = 0;
  for (const d of it.days) {
    let prev = d.start;
    for (const x of d.stops) {
      best = Math.max(best, x.arrive - x.travel_in - prev);
      prev = x.depart;
    }
    best = Math.max(best, dayEnd - d.return_travel - prev);
  }
  return Math.max(0, best);
}

/** After a manual reorder: re-time the day from the old legs. Only an estimate until re-optimized. */
function retime(day: Day, stops: Stop[]): Day {
  let t = day.start;
  const out = stops.map((x) => {
    const arrive = t + x.travel_in + x.meal_break_before;
    const start = Math.max(arrive, x.place.open_min, x.locked_start ?? 0);
    const depart = start + (x.depart - x.start);
    t = depart;
    return {
      ...x,
      arrive,
      start,
      depart,
      wait: start - arrive,
      golden: start >= x.place.golden_start && start < x.place.golden_end,
      late_by: Math.max(0, depart - x.place.close_min),
    };
  });
  return { ...day, stops: out, return_time: t + day.meal_break_before_return + day.return_travel };
}

function DayTab({ day, label, active, over, onClick }: { day: number; label: string; active: boolean; over: boolean; onClick: () => void }) {
  const { setNodeRef } = useDroppable({ id: `day-${day}` });
  return (
    <button
      ref={setNodeRef}
      type="button"
      role="tab"
      aria-selected={active}
      className={cx(s.dayTab, active && s.dayTabOn, over && s.dayTabDrop)}
      onClick={onClick}
      title={`${label} — drop a stop here to move it`}
    >
      {label}
    </button>
  );
}

function OptimizingDialog({ job, onCancel }: { job: OptimizeJob | null; onCancel: () => void }) {
  const steps = job?.steps ?? [
    { key: "hours", label: "Opening hours checked", done: false },
    { key: "travel", label: "Travel times loaded", done: false },
    { key: "search", label: "Searching for the best order", done: false },
  ];
  const pct = job ? Math.min(100, (100 * job.generation) / Math.max(1, job.max_generations)) : 0;
  return (
    <Modal title="Building your itinerary…">
      <p className={s.sub} aria-live="polite">
        {job && job.generation > 0
          ? `Generation ${job.generation} of ${job.max_generations} · best plan so far: ${job.best_stops} stops, ${job.best_travel_min} min travel`
          : "Preparing the places and travel times…"}
      </p>
      <span className={s.progress} role="progressbar" aria-label="Optimization progress" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </span>
      <ul className={s.jobSteps}>
        {steps.map((x) => (
          <li key={x.key} data-done={x.done}>
            <span aria-hidden>{x.done ? "✓" : ""}</span>
            {x.label}
          </li>
        ))}
      </ul>
      <div>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Modal>
  );
}

function PlanFitDialog({ fit, onApply, onBack, onClose }: { fit: PlanFit; onApply: (f: PlanFix) => void; onBack: () => void; onClose: () => void }) {
  const fixes = fit.fixes;
  const [pick, setPick] = useState(() => Math.max(0, fixes.findIndex((f) => f.recommended)));
  const where = fit.day != null ? `on Day ${fit.day + 1}, but the day has` : "over the trip, but the trip has";
  return (
    <Modal title="Not all must-visit places fit" icon={<span className={s.warnIcon}>⚠</span>} onClose={onClose}>
      <p className={s.sub}>
        Your must-visit places need {duration(fit.needed_min)} {where} only {duration(fit.available_min)} left after travel.
        {fixes.length ? " Choose one fix:" : " Remove a place or add time, then try again."}
      </p>
      <div className={s.fixes} role="radiogroup" aria-label="Fixes">
        {fixes.map((f, i) => (
          <button key={f.label} type="button" role="radio" aria-checked={pick === i} className={cx(s.fix, pick === i && s.fixOn)} onClick={() => setPick(i)}>
            <span>{f.label}</span>
            {f.recommended ? <span className={s.fixTag}>Recommended</span> : !f.fits && <span className={s.fixNote}>may still not fit</span>}
          </button>
        ))}
      </div>
      <div className={s.dialogActions}>
        <Button variant="outline" onClick={onBack}>
          Back to places
        </Button>
        <Button onClick={() => fixes[pick] && onApply(fixes[pick])} disabled={!fixes.length}>
          Apply and re-optimize
        </Button>
      </div>
    </Modal>
  );
}

type Edit = { text: string; before: TripState };

export function ItineraryScreen() {
  const router = useRouter();
  const { state, dispatch, cities, optimize, cancel, job, optimizing, saveTrip, error, clearError, hydrated } = useTrip();
  const [hovered, setHovered] = useState<number | null>(null);
  const [overDay, setOverDay] = useState<number | null>(null);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [movedId, setMovedId] = useState<number | null>(null);
  const [dismissedFit, setDismissedFit] = useState<PlanFit | null>(null);
  const [saving, setSaving] = useState(false);
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

  const reoptimize = (opts: { locks?: Lock[]; patch?: Partial<OptimizeRequest> } = {}) => {
    setEdit(null);
    setMovedId(null);
    dispatch({ type: "edit", event: { kind: "reoptimize" } });
    return optimize({ ...opts, seed: !opts.patch });
  };

  const top = <TopBar items={planNav(state, "/plan/itinerary")} active="/plan/itinerary" right={<TripSummary state={state} />} />;
  const dialogs = (
    <>
      {optimizing && <OptimizingDialog job={job} onCancel={cancel} />}
      {!optimizing && it?.plan_fit && dismissedFit !== it.plan_fit && (
        <PlanFitDialog
          key={it.fitness}
          fit={it.plan_fit}
          onClose={() => setDismissedFit(it.plan_fit!)}
          onBack={() => router.push("/plan/places")}
          onApply={(f) => void reoptimize({ patch: f.patch })}
        />
      )}
    </>
  );

  if (!hydrated) return <div className={s.screen}>{top}</div>;
  if (!it) {
    return (
      <div className={s.screen}>
        {top}
        <div className={s.emptyState}>
          {!optimizing && (
            <div>
              <h1 className={s.h1}>No itinerary yet</h1>
              {error ? (
                <p className={s.error} role="alert">
                  {error}
                </p>
              ) : (
                <p>Pick a few places first — ChronoTrip will put them in the right order.</p>
              )}
              <ButtonLink href="/plan/places">Pick places</ButtonLink>
            </div>
          )}
        </div>
        {dialogs}
      </div>
    );
  }

  const day = it.days[Math.min(state.activeDay, it.days.length - 1)];
  const stops = day.stops;
  const hoursMet = stops.every((x) => x.late_by === 0) && day.warnings.length === 0;
  const tripWarnings = [...(it.warnings ?? []), ...day.warnings];
  const gap = largestGap(it, state.dayEnd);

  const remember = (text: string) => setEdit({ text, before: state });

  const toggleLock = (stop: Stop) => {
    const id = stop.place.id;
    if (lockedIds.has(id)) {
      dispatch({ type: "unlock", placeId: id });
      dispatch({ type: "edit", event: { kind: "unlock", place_id: id, day: day.day } });
    } else {
      dispatch({ type: "lock", lock: { place_id: id, day: day.day, start: stop.start } });
      dispatch({ type: "edit", event: { kind: "lock", place_id: id, day: day.day, value: stop.start } });
    }
  };

  const remove = (stop: Stop) => {
    remember(`You removed ${stop.place.label}. Re-optimize to fill the gap.`);
    setMovedId(null);
    dispatch({ type: "removeStop", placeId: stop.place.id });
    dispatch({ type: "edit", event: { kind: "remove", place_id: stop.place.id, day: day.day } });
  };

  const onDragOver = (e: DragOverEvent) => {
    const id = String(e.over?.id ?? "");
    setOverDay(id.startsWith("day-") ? Number(id.slice(4)) : null);
  };

  // FR-05: a moved stop is locked (day + new time). Same day: re-time locally and wait for
  // "Re-optimize"; another day: re-optimize the rest right away.
  const onDragEnd = (e: DragEndEvent) => {
    setOverDay(null);
    const placeId = Number(e.active.id);
    const overId = String(e.over?.id ?? "");
    if (!overId || overId === String(placeId)) return;
    if (overId.startsWith("day-")) {
      const target = Number(overId.slice(4));
      if (target === day.day) return;
      const lock = { place_id: placeId, day: target, start: null };
      dispatch({ type: "lock", lock });
      dispatch({ type: "activeDay", day: target });
      dispatch({ type: "edit", event: { kind: "move", place_id: placeId, day: target } });
      void reoptimize({ locks: [...state.locks.filter((l) => l.place_id !== placeId), lock] });
      return;
    }
    const from = stops.findIndex((x) => x.place.id === placeId);
    const to = stops.findIndex((x) => x.place.id === Number(overId));
    if (from < 0 || to < 0) return;
    const moved = { ...stops[from], locked_start: null };
    const next = retime(day, arrayMove(stops, from, to).map((x) => (x.place.id === placeId ? moved : x)));
    const at = next.stops.find((x) => x.place.id === placeId)!.start;
    remember(`You moved ${moved.place.label} to ${clock(at)}.`);
    setMovedId(placeId);
    dispatch({ type: "itinerary", itinerary: { ...it, days: it.days.map((d) => (d.day === day.day ? next : d)) } });
    dispatch({ type: "lock", lock: { place_id: placeId, day: day.day, start: at } });
    dispatch({ type: "edit", event: { kind: "move", place_id: placeId, day: day.day, value: at } });
  };

  const save = async () => {
    setSaving(true);
    const id = await saveTrip();
    setSaving(false);
    if (id != null) router.push(`/plan/trips?id=${id}`);
  };

  return (
    <div className={s.screen}>
      {top}
      <div className={s.body}>
        <aside className={cx(s.panel, s.panelWide)}>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragOver={onDragOver} onDragEnd={onDragEnd} onDragCancel={() => setOverDay(null)}>
            <div className={s.head}>
              <h1 className={s.h1}>{dayTitle(state.startDate, day.day)}</h1>
              <div className={s.dayTabs} role="tablist" aria-label="Day">
                {it.days.map((d) => (
                  <DayTab
                    key={d.day}
                    day={d.day}
                    label={`Day ${d.day + 1}`}
                    active={d.day === day.day}
                    over={overDay === d.day}
                    onClick={() => dispatch({ type: "activeDay", day: d.day })}
                  />
                ))}
              </div>
            </div>
            <p className={s.summary}>
              {stops.length} stops · {day.travel_minutes} min travel · back at {state.stay?.label ?? "your stay"} {clock(day.return_time)}
              {stops.length > 0 && (
                <Pill small tone={hoursMet ? "ok" : "warn"}>
                  {hoursMet ? "All opening hours met" : "Check opening hours"}
                </Pill>
              )}
            </p>

            {edit && (
              <div className={s.editBanner} role="status">
                <span className={s.warnIcon} aria-hidden>
                  ⚠
                </span>
                <span>
                  <strong>{edit.text}</strong>
                  <span>Times below are estimated. Re-optimize to recheck the whole day.</span>
                </span>
                <button
                  type="button"
                  className={s.undo}
                  onClick={() => {
                    dispatch({ type: "load", state: edit.before });
                    setEdit(null);
                    setMovedId(null);
                  }}
                >
                  Undo
                </button>
              </div>
            )}
            {tripWarnings.length > 0 && (
              <div className={s.warnings} role="status">
                {tripWarnings.map((w) => (
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
                      moved={movedId === x.place.id}
                      onLockToggle={() => toggleLock(x)}
                      onRemove={() => remove(x)}
                      onHover={setHovered}
                    />
                  </Fragment>
                ))}
              </SortableContext>
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
              <div className={s.notScheduledHead}>
                <span className={s.notScheduledTitle}>Not scheduled ({it.unscheduled.length})</span>
                <button
                  type="button"
                  className={s.linkButton}
                  title="Mark these places as must-visit; the optimizer then suggests how to make room"
                  onClick={() => void reoptimize({ patch: { must_visit: [...new Set([...state.mustVisit, ...it.unscheduled.map((p) => p.id)])] } })}
                >
                  Make room
                </button>
              </div>
              {it.unscheduled.map((p) => (
                <span key={p.id} className={s.notScheduledList}>
                  {p.label} · {p.ward} needs ≈ {duration(p.duration)}; {gap > 0 ? `the largest free gap is ${duration(gap)}` : "no free time is left"}.
                </span>
              ))}
            </div>
          )}
          <div className={s.actions2}>
            <ButtonLink href="/plan/places" variant="outline">
              Back to places
            </ButtonLink>
            <Button onClick={save} loading={saving}>
              {state.tripRef ? "Save changes" : "Save trip"}
            </Button>
          </div>
          <p className={s.meta}>
            Memetic GA · {it.generations} generations in {it.runtime_s}s · travel times{" "}
            {it.travel_source === "osrm" ? "from OSRM (no live traffic)" : "estimated from distance"} · all place attributes are estimates
          </p>
        </aside>

        <div className={s.mapArea}>
          <Button className={s.mapButton} onClick={() => void reoptimize()} loading={optimizing}>
            Re-optimize
          </Button>
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
      {dialogs}
    </div>
  );
}
