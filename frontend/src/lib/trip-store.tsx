"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { saveTripRef, type TripRef } from "./saved-trips";
import type { City, Day, EditEvent, Interest, Itinerary, Lock, OptimizeJob, OptimizeRequest, Place, Point, Preferences, Stop, Trip } from "./types";

export const MAX_PLACES = 30;
const STORAGE_KEY = "chronotrip.trip.v1";

export interface TripState {
  city: string;
  stay: Point | null;
  days: number;
  dayStart: number;
  dayEnd: number;
  prefs: Preferences;
  selected: Place[];
  locks: Lock[];
  itinerary: Itinerary | null;
  activeDay: number;
  startDate: string | null; // YYYY-MM-DD
  interests: Interest[];
  mustVisit: number[];
  tripRef: TripRef | null; // the saved trip being edited (T4)
  edits: EditEvent[]; // sent anonymously on save when the traveler agreed
}

export const INTERESTS: { key: Interest; label: string }[] = [
  { key: "food", label: "Food" },
  { key: "culture", label: "Culture" },
  { key: "nature", label: "Nature" },
  { key: "nightlife", label: "Nightlife" },
  { key: "shopping", label: "Shopping" },
];

const initial: TripState = {
  city: "Ho Chi Minh City",
  stay: null,
  days: 1,
  dayStart: 8 * 60,
  dayEnd: 21 * 60 + 30,
  prefs: { pace: 0.5, travel: 0.5, strictness: 0.5 },
  selected: [],
  locks: [],
  itinerary: null,
  activeDay: 0,
  startDate: null,
  interests: [],
  mustVisit: [],
  tripRef: null,
  edits: [],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPoint(value: unknown): value is Point {
  return isRecord(value) && isNumber(value.lat) && isNumber(value.lon) && typeof value.label === "string";
}

function isPreferences(value: unknown): value is Preferences {
  return (
    isRecord(value) &&
    [value.pace, value.travel, value.strictness].every((item) => isNumber(item) && item >= 0 && item <= 1)
  );
}

function isPlace(value: unknown): value is Place {
  if (!isRecord(value)) return false;
  return (
    [
      value.id,
      value.lat,
      value.lon,
      value.effort,
      value.score,
      value.duration,
      value.open_min,
      value.close_min,
      value.golden_start,
      value.golden_end,
      value.n_checkins,
    ].every(isNumber) &&
    [value.city, value.ward, value.category, value.label, value.group].every((item) => typeof item === "string") &&
    (value.confidence === "high" || value.confidence === "medium" || value.confidence === "low") &&
    typeof value.estimated === "boolean"
  );
}

function isLock(value: unknown): value is Lock {
  return (
    isRecord(value) &&
    isNumber(value.place_id) &&
    Number.isInteger(value.day) &&
    (value.start === null || isNumber(value.start))
  );
}

function isStop(value: unknown): value is Stop {
  return (
    isRecord(value) &&
    isPlace(value.place) &&
    [value.arrive, value.start, value.depart, value.wait, value.travel_in, value.meal_break_before, value.late_by].every(isNumber) &&
    typeof value.golden === "boolean" &&
    typeof value.locked === "boolean" &&
    (value.locked_start === null || isNumber(value.locked_start))
  );
}

function isDay(value: unknown): value is Day {
  return (
    isRecord(value) &&
    [value.day, value.start, value.return_time, value.return_travel, value.meal_break_before_return, value.travel_minutes, value.wait_minutes].every(isNumber) &&
    Array.isArray(value.stops) &&
    value.stops.every(isStop) &&
    Array.isArray(value.warnings) &&
    value.warnings.every((warning) => typeof warning === "string")
  );
}

function isItinerary(value: unknown): value is Itinerary {
  return (
    isRecord(value) &&
    Array.isArray(value.days) &&
    value.days.every(isDay) &&
    Array.isArray(value.unscheduled) &&
    value.unscheduled.every(isPlace) &&
    [value.fitness, value.generations, value.runtime_s].every(isNumber) &&
    (value.travel_source === "osrm" || value.travel_source === "estimate") &&
    isRecord(value.weights) &&
    Object.values(value.weights).every(isNumber)
  );
}

function restoredTrip(value: unknown): TripState {
  if (!isRecord(value)) return initial;
  const days = isNumber(value.days) && Number.isInteger(value.days) && value.days >= 1 && value.days <= 3 ? value.days : initial.days;
  const dayStart = isNumber(value.dayStart) && value.dayStart >= 0 && value.dayStart <= 24 * 60 ? value.dayStart : initial.dayStart;
  const dayEnd = isNumber(value.dayEnd) && value.dayEnd >= dayStart + 120 && value.dayEnd <= 24 * 60 ? value.dayEnd : initial.dayEnd;
  const selected = Array.isArray(value.selected)
    ? value.selected.filter(isPlace).filter((place, index, places) => places.findIndex((candidate) => candidate.id === place.id) === index)
    : [];
  const selectedIds = new Set(selected.map((place) => place.id));
  const locks = Array.isArray(value.locks)
    ? value.locks
        .filter(isLock)
        .filter((lock) => selectedIds.has(lock.place_id) && lock.day >= 0 && lock.day < days)
        .filter((lock, index, all) => all.findIndex((candidate) => candidate.place_id === lock.place_id) === index)
    : [];
  const ref = value.tripRef;
  const interests = Array.isArray(value.interests) ? value.interests : [];
  return {
    city: typeof value.city === "string" && value.city ? value.city : initial.city,
    stay: value.stay === null || isPoint(value.stay) ? value.stay : null,
    days,
    dayStart,
    dayEnd,
    prefs: isPreferences(value.prefs) ? value.prefs : initial.prefs,
    selected,
    locks,
    itinerary: isItinerary(value.itinerary) ? value.itinerary : null,
    activeDay: isNumber(value.activeDay) && Number.isInteger(value.activeDay) && value.activeDay >= 0 && value.activeDay < days ? value.activeDay : 0,
    startDate: typeof value.startDate === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value.startDate) ? value.startDate : null,
    interests: INTERESTS.map((i) => i.key).filter((k) => interests.includes(k)),
    mustVisit: Array.isArray(value.mustVisit) ? value.mustVisit.filter((id): id is number => isNumber(id) && selectedIds.has(id)) : [],
    tripRef: isRecord(ref) && isNumber(ref.id) && typeof ref.token === "string" ? { id: ref.id, token: ref.token } : null,
    edits: [], // never restored: only this session's edits are offered for upload
  };
}

type Action =
  | { type: "hydrate"; state: TripState }
  | { type: "city"; city: string }
  | { type: "stay"; stay: Point }
  | { type: "days"; days: number }
  | { type: "hours"; dayStart: number; dayEnd: number }
  | { type: "prefs"; prefs: Partial<Preferences> }
  | { type: "startDate"; date: string | null }
  | { type: "interests"; interests: Interest[] }
  | { type: "toggle"; place: Place }
  | { type: "add"; places: Place[] }
  | { type: "mustVisit"; place: Place; on: boolean }
  | { type: "removeStop"; placeId: number }
  | { type: "clear" }
  | { type: "reset" }
  | { type: "lock"; lock: Lock }
  | { type: "unlock"; placeId: number }
  | { type: "patch"; patch: Partial<OptimizeRequest> }
  | { type: "itinerary"; itinerary: Itinerary | null }
  | { type: "activeDay"; day: number }
  | { type: "edit"; event: EditEvent }
  | { type: "saved"; ref: TripRef | null }
  | { type: "load"; state: TripState };

// actions that do not change the optimisation request keep a running job alive
const KEEPS_JOB = new Set<Action["type"]>(["itinerary", "activeDay", "edit", "saved", "interests", "hydrate"]);

function withoutPlace(s: TripState, id: number): TripState {
  return {
    ...s,
    selected: s.selected.filter((p) => p.id !== id),
    locks: s.locks.filter((l) => l.place_id !== id),
    mustVisit: s.mustVisit.filter((m) => m !== id),
  };
}

function reducer(s: TripState, a: Action): TripState {
  switch (a.type) {
    case "hydrate":
    case "load":
      return a.state;
    case "reset":
      return { ...initial, city: s.city, interests: s.interests, prefs: s.prefs };
    case "city":
      return a.city === s.city
        ? s
        : { ...initial, city: a.city, days: s.days, dayStart: s.dayStart, dayEnd: s.dayEnd, prefs: s.prefs, startDate: s.startDate, interests: s.interests };
    case "stay":
      return { ...s, stay: a.stay };
    case "days": {
      const days = Math.min(3, Math.max(1, a.days));
      return { ...s, days, locks: s.locks.filter((l) => l.day < days), activeDay: Math.min(s.activeDay, days - 1) };
    }
    case "hours":
      return { ...s, dayStart: a.dayStart, dayEnd: a.dayEnd };
    case "prefs":
      return { ...s, prefs: { ...s.prefs, ...a.prefs } };
    case "startDate":
      return { ...s, startDate: a.date };
    case "interests":
      return { ...s, interests: a.interests };
    case "toggle": {
      if (s.selected.some((p) => p.id === a.place.id)) return withoutPlace(s, a.place.id);
      if (s.selected.length >= MAX_PLACES) return s;
      return { ...s, selected: [...s.selected, a.place] };
    }
    case "add": {
      const ids = new Set(s.selected.map((p) => p.id));
      const fresh = a.places.filter((p) => !ids.has(p.id)).slice(0, MAX_PLACES - s.selected.length);
      return { ...s, selected: [...s.selected, ...fresh] };
    }
    case "mustVisit": {
      if (!a.on) return { ...s, mustVisit: s.mustVisit.filter((m) => m !== a.place.id) };
      const has = s.selected.some((p) => p.id === a.place.id);
      if (!has && s.selected.length >= MAX_PLACES) return s;
      return {
        ...s,
        selected: has ? s.selected : [...s.selected, a.place],
        mustVisit: [...s.mustVisit.filter((m) => m !== a.place.id), a.place.id],
      };
    }
    case "removeStop": {
      const next = withoutPlace(s, a.placeId);
      if (!s.itinerary) return next;
      return {
        ...next,
        itinerary: {
          ...s.itinerary,
          days: s.itinerary.days.map((d) => ({ ...d, stops: d.stops.filter((x) => x.place.id !== a.placeId) })),
          unscheduled: s.itinerary.unscheduled.filter((p) => p.id !== a.placeId),
        },
      };
    }
    case "clear":
      return { ...s, selected: [], locks: [], mustVisit: [], itinerary: null };
    case "lock":
      return { ...s, locks: [...s.locks.filter((l) => l.place_id !== a.lock.place_id), a.lock] };
    case "unlock":
      return { ...s, locks: s.locks.filter((l) => l.place_id !== a.placeId) };
    case "patch": {
      // a PlanFix patch: the request fields to replace (docs/figma-api.md §3.1)
      const p = a.patch;
      let next = p.days ? reducer(s, { type: "days", days: p.days }) : s;
      if (p.day_start != null || p.day_end != null)
        next = { ...next, dayStart: p.day_start ?? next.dayStart, dayEnd: p.day_end ?? next.dayEnd };
      if (p.place_ids) {
        const keep = new Set(p.place_ids);
        next = {
          ...next,
          selected: next.selected.filter((x) => keep.has(x.id)),
          locks: next.locks.filter((l) => keep.has(l.place_id)),
          mustVisit: next.mustVisit.filter((m) => keep.has(m)),
        };
      }
      if (p.locks) next = { ...next, locks: p.locks };
      if (p.must_visit) next = { ...next, mustVisit: p.must_visit };
      return next;
    }
    case "itinerary":
      return { ...s, itinerary: a.itinerary, activeDay: a.itinerary ? Math.min(s.activeDay, a.itinerary.days.length - 1) : 0 };
    case "activeDay":
      return { ...s, activeDay: a.day };
    case "edit":
      return { ...s, edits: [...s.edits, a.event].slice(-500) };
    case "saved":
      return { ...s, tripRef: a.ref, edits: a.ref ? [] : s.edits };
  }
}

export function buildRequest(s: TripState, opts: { locks?: Lock[]; seed?: boolean } = {}): OptimizeRequest | null {
  if (!s.stay || s.selected.length === 0) return null;
  const ids = new Set(s.selected.map((p) => p.id));
  return {
    city: s.city,
    place_ids: s.selected.map((p) => p.id),
    days: s.days,
    start_date: s.startDate,
    day_start: s.dayStart,
    day_end: s.dayEnd,
    stay: s.stay,
    preferences: s.prefs,
    locks: (opts.locks ?? s.locks).filter((l) => ids.has(l.place_id) && l.day < s.days),
    must_visit: s.mustVisit.filter((id) => ids.has(id)),
    seed_plan:
      opts.seed && s.itinerary
        ? s.itinerary.days.map((d) => d.stops.map((x) => x.place.id).filter((id) => ids.has(id)))
        : null,
  };
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

type OptimizeOpts = { locks?: Lock[]; seed?: boolean; patch?: Partial<OptimizeRequest> };

interface TripContextValue {
  state: TripState;
  hydrated: boolean;
  cities: City[];
  dispatch: React.Dispatch<Action>;
  optimize: (opts?: OptimizeOpts) => Promise<Itinerary | null>;
  cancel: () => void;
  job: OptimizeJob | null;
  optimizing: boolean;
  saveTrip: () => Promise<number | null>;
  openTrip: (trip: Trip, ref: TripRef) => Promise<void>;
  error: string | null;
  clearError: () => void;
}

const TripContext = createContext<TripContextValue | null>(null);

export function TripProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatchState] = useReducer(reducer, initial);
  const [hydrated, setHydrated] = useState(false);
  const [cities, setCities] = useState<City[]>([]);
  const [optimizing, setOptimizing] = useState(false);
  const [job, setJob] = useState<OptimizeJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const jobId = useRef<string | null>(null);
  const requestVersion = useRef(0);

  const invalidateOptimization = useCallback(() => {
    requestVersion.current += 1;
    if (jobId.current) api.cancelJob(jobId.current).catch(() => {});
    jobId.current = null;
    setOptimizing(false);
    setJob(null);
  }, []);

  const dispatch = useCallback<React.Dispatch<Action>>(
    (action) => {
      if (!KEEPS_JOB.has(action.type)) invalidateOptimization();
      dispatchState(action);
    },
    [invalidateOptimization],
  );

  // Restore the trip from this tab's session after mount. Reading storage during
  // render would make the server HTML and the first client render disagree.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (raw) dispatchState({ type: "hydrate", state: restoredTrip(JSON.parse(raw)) });
    } catch {
      /* storage unavailable or corrupted: start fresh */
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time sync from sessionStorage
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* quota / private mode */
    }
  }, [state, hydrated]);

  useEffect(() => {
    let alive = true;
    api
      .cities()
      .then((list) => alive && setCities(list))
      .catch((e: ApiError) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  // default stay for the city
  useEffect(() => {
    if (!hydrated || state.stay) return;
    const c = cities.find((x) => x.name === state.city);
    if (!c) return;
    const id = window.setTimeout(() => {
      dispatch({ type: "stay", stay: { lat: c.stay.lat, lon: c.stay.lon, label: c.stay.label } });
    }, 0);
    return () => window.clearTimeout(id);
  }, [hydrated, cities, state.city, state.stay, dispatch]);

  // T3 "Building your itinerary…": start a job and poll it (docs/figma-api.md §3.2)
  const optimize = useCallback(
    async (opts: OptimizeOpts = {}) => {
      const base = buildRequest(state, opts);
      if (!base) return null;
      invalidateOptimization();
      const version = requestVersion.current;
      if (opts.patch) dispatchState({ type: "patch", patch: opts.patch });
      setOptimizing(true);
      setError(null);
      try {
        let j = await api.startJob({ ...base, ...opts.patch });
        jobId.current = j.id;
        while (j.status === "running") {
          if (version !== requestVersion.current) return null;
          setJob(j);
          await sleep(400);
          if (version !== requestVersion.current) return null;
          j = await api.pollJob(j.id);
        }
        if (version !== requestVersion.current) return null;
        if (j.status === "done" && j.result) {
          dispatchState({ type: "itinerary", itinerary: j.result });
          return j.result;
        }
        if (j.status === "failed") setError(j.error ?? "The optimizer failed. Please try again.");
        return null;
      } catch (e) {
        if (version !== requestVersion.current) return null;
        setError(e instanceof ApiError ? e.message : "Something went wrong while optimizing.");
        return null;
      } finally {
        if (version === requestVersion.current) {
          jobId.current = null;
          setOptimizing(false);
          setJob(null);
        }
      }
    },
    [state, invalidateOptimization],
  );

  const saveTrip = useCallback(async () => {
    const request = buildRequest(state);
    if (!request) return null;
    setError(null);
    try {
      let trip: Trip;
      let ref = state.tripRef;
      if (ref) {
        trip = await api.updateTrip(ref.id, ref.token, { request, itinerary: state.itinerary });
      } else {
        const created = await api.createTrip({ request, itinerary: state.itinerary });
        ref = { id: created.id, token: created.edit_token };
        saveTripRef(ref);
        trip = created;
      }
      if (trip.improve_estimates && state.edits.length) await api.sendEdits(ref.id, ref.token, state.edits).catch(() => {});
      dispatchState({ type: "saved", ref });
      return ref.id;
    } catch (e) {
      // a stale token (trip deleted elsewhere) gives 404: the next save creates a new trip
      if (e instanceof ApiError && e.status === 404) dispatchState({ type: "saved", ref: null });
      setError(e instanceof ApiError ? e.message : "Could not save the trip.");
      return null;
    }
  }, [state]);

  const openTrip = useCallback(
    async (trip: Trip, ref: TripRef) => {
      invalidateOptimization();
      const r = trip.request;
      const known = new Map<number, Place>();
      trip.itinerary?.days.forEach((d) => d.stops.forEach((x) => known.set(x.place.id, x.place)));
      trip.itinerary?.unscheduled.forEach((p) => known.set(p.id, p));
      const ids = r.place_ids.filter((id) => !trip.stale_places.includes(id));
      const missing = ids.filter((id) => !known.has(id));
      const fetched = await Promise.all(missing.map((id) => api.place(id).catch(() => null)));
      fetched.forEach((p) => p && known.set(p.id, p));
      dispatchState({
        type: "load",
        state: restoredTrip({
          city: r.city,
          stay: r.stay,
          days: r.days,
          dayStart: r.day_start,
          dayEnd: r.day_end,
          prefs: r.preferences,
          selected: ids.map((id) => known.get(id)).filter(Boolean),
          locks: r.locks,
          // the saved plan refers to places the active model no longer has: plan again
          itinerary: trip.stale_places.length ? null : trip.itinerary,
          startDate: r.start_date ?? null,
          interests: state.interests,
          mustVisit: r.must_visit ?? [],
          tripRef: ref,
        }),
      });
    },
    [invalidateOptimization, state.interests],
  );

  const value = useMemo(
    () => ({
      state,
      hydrated,
      cities,
      dispatch,
      optimize,
      cancel: invalidateOptimization,
      job,
      optimizing,
      saveTrip,
      openTrip,
      error,
      clearError: () => setError(null),
    }),
    [state, hydrated, cities, dispatch, optimize, invalidateOptimization, job, optimizing, saveTrip, openTrip, error],
  );
  return <TripContext.Provider value={value}>{children}</TripContext.Provider>;
}

export function useTrip() {
  const ctx = useContext(TripContext);
  if (!ctx) throw new Error("useTrip must be used inside <TripProvider>");
  return ctx;
}
