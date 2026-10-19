/** Minutes since midnight -> "08:15" (wraps past midnight). */
export function clock(minutes: number): string {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** "08:15" -> 495 */
export function parseClock(value: string): number {
  const [h, m] = value.split(":").map(Number);
  return h * 60 + (m || 0);
}

/** 85 -> "85 min", 135 -> "2 h 15 min" */
export function duration(minutes: number): string {
  const m = Math.round(minutes);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r ? `${h} h ${r} min` : `${h} h`;
}

export function timeRange(start: number, end: number): string {
  return `${clock(start)}–${clock(end)}`;
}
