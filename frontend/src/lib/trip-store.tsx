"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { City, Day, Itinerary, Lock, Place, Point, Preferences, Stop } from "./types";

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
}

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
  };
}

type Action =
  | { type: "hydrate"; state: TripState }
  | { type: "city"; city: string }
  | { type: "stay"; stay: Point }
  | { type: "days"; days: number }
  | { type: "hours"; dayStart: number; dayEnd: number }
  | { type: "prefs"; prefs: Partial<Preferences> }
  | { type: "toggle"; place: Place }
  | { type: "add"; places: Place[] }
  | { type: "clear" }
  | { type: "lock"; lock: Lock }
  | { type: "unlock"; placeId: number }
  | { type: "itinerary"; itinerary: Itinerary | null }
  | { type: "activeDay"; day: number };

function reducer(s: TripState, a: Action): TripState {
  switch (a.type) {
    case "hydrate":
      return a.state;
    case "city":
      return a.city === s.city ? s : { ...initial, city: a.city, days: s.days, dayStart: s.dayStart, dayEnd: s.dayEnd, prefs: s.prefs };
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
    case "toggle": {
      const has = s.selected.some((p) => p.id === a.place.id);
      if (has)
        return {
          ...s,
          selected: s.selected.filter((p) => p.id !== a.place.id),
          locks: s.locks.filter((l) => l.place_id !== a.place.id),
        };
      if (s.selected.length >= MAX_PLACES) return s;
      return { ...s, selected: [...s.selected, a.place] };
    }
    case "add": {
      const ids = new Set(s.selected.map((p) => p.id));
      const fresh = a.places.filter((p) => !ids.has(p.id)).slice(0, MAX_PLACES - s.selected.length);
      return { ...s, selected: [...s.selected, ...fresh] };
    }
    case "clear":
      return { ...s, selected: [], locks: [], itinerary: null };
    case "lock":
      return { ...s, locks: [...s.locks.filter((l) => l.place_id !== a.lock.place_id), a.lock] };
    case "unlock":
      return { ...s, locks: s.locks.filter((l) => l.place_id !== a.placeId) };
    case "itinerary":
      return { ...s, itinerary: a.itinerary, activeDay: a.itinerary ? Math.min(s.activeDay, a.itinerary.days.length - 1) : 0 };
    case "activeDay":
      return { ...s, activeDay: a.day };
  }
}

interface TripContextValue {
  state: TripState;
  hydrated: boolean;
  cities: City[];
  dispatch: React.Dispatch<Action>;
  optimize: (opts?: { locks?: Lock[]; seed?: boolean }) => Promise<Itinerary | null>;
  optimizing: boolean;
  error: string | null;
  clearError: () => void;
}

const TripContext = createContext<TripContextValue | null>(null);

export function TripProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatchState] = useReducer(reducer, initial);
  const [hydrated, setHydrated] = useState(false);
  const [cities, setCities] = useState<City[]>([]);
  const [optimizing, setOptimizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);

  const invalidateOptimization = useCallback(() => {
    requestVersion.current += 1;
    abort.current?.abort();
    abort.current = null;
    setOptimizing(false);
  }, []);

  const dispatch = useCallback<React.Dispatch<Action>>(
    (action) => {
      if (action.type !== "itinerary" && action.type !== "activeDay") invalidateOptimization();
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

  const optimize = useCallback(
    async (opts: { locks?: Lock[]; seed?: boolean } = {}) => {
      if (!state.stay || state.selected.length === 0) return null;
      const previous = abort.current;
      const ctrl = new AbortController();
      abort.current = ctrl;
      const version = ++requestVersion.current;
      previous?.abort();
      const locks = opts.locks ?? state.locks;
      setOptimizing(true);
      setError(null);
      try {
        const ids = new Set(state.selected.map((p) => p.id));
        const seedPlan =
          opts.seed && state.itinerary
            ? state.itinerary.days.map((d) => d.stops.map((s) => s.place.id).filter((id) => ids.has(id)))
            : null;
        const it = await api.optimize(
          {
            city: state.city,
            place_ids: state.selected.map((p) => p.id),
            days: state.days,
            day_start: state.dayStart,
            day_end: state.dayEnd,
            stay: state.stay,
            preferences: state.prefs,
            locks: locks.filter((l) => ids.has(l.place_id) && l.day < state.days),
            seed_plan: seedPlan,
          },
          ctrl.signal,
        );
        if (version !== requestVersion.current) return null;
        dispatchState({ type: "itinerary", itinerary: it });
        return it;
      } catch (e) {
        if (version !== requestVersion.current || (e as Error).name === "AbortError") return null;
        setError(e instanceof ApiError ? e.message : "Something went wrong while optimizing.");
        return null;
      } finally {
        if (abort.current === ctrl) {
          abort.current = null;
          setOptimizing(false);
        }
      }
    },
    [state],
  );

  const value = useMemo(
    () => ({ state, hydrated, cities, dispatch, optimize, optimizing, error, clearError: () => setError(null) }),
    [state, hydrated, cities, dispatch, optimize, optimizing, error],
  );
  return <TripContext.Provider value={value}>{children}</TripContext.Provider>;
}

export function useTrip() {
  const ctx = useContext(TripContext);
  if (!ctx) throw new Error("useTrip must be used inside <TripProvider>");
  return ctx;
}
