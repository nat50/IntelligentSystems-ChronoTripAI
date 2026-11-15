// T4: no accounts on the backend. Each saved trip has a secret edit token that the
// API returns once; the browser keeps the {id, token} pairs. Clearing storage loses
// edit access to those trips (docs/figma-api.md §3.3).
const KEY = "chronotrip.trips.v1";

export interface TripRef {
  id: number;
  token: string;
}

export function loadTripRefs(): TripRef[] {
  try {
    const list: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(list)
      ? list.filter((r): r is TripRef => typeof r?.id === "number" && typeof r?.token === "string")
      : [];
  } catch {
    return [];
  }
}

export function saveTripRef(ref: TripRef) {
  const refs = [ref, ...loadTripRefs().filter((r) => r.id !== ref.id)];
  try {
    localStorage.setItem(KEY, JSON.stringify(refs));
  } catch {
    /* private mode: the trip stays reachable only in this session */
  }
}
