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

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** closed_days uses Python weekday(): 0 = Monday. [0] -> "Closed on Mondays" */
export function closedText(days?: number[]): string {
  if (!days?.length) return "";
  if (days.length === 1) return `Closed on ${WEEKDAYS[days[0]]}s`;
  return `Closed on ${days.map((d) => WEEKDAYS[d].slice(0, 3)).join(", ")}`;
}

/** "Open 08:00–17:00 · Closed on Mondays", or an estimate from check-ins */
export function hoursText(p: { open_min: number; close_min: number; hours_source?: string; closed_days?: number[] }): string {
  if (p.hours_source === "crawl") return [`Open ${timeRange(p.open_min, p.close_min)}`, closedText(p.closed_days)].filter(Boolean).join(" · ");
  return `Usually open ${timeRange(p.open_min, p.close_min)} · estimated`;
}

/** "65–105 min" (M3 q25–q75), or "≈ 85 min" when no range is known */
export function durationRange(p: { duration: number; duration_lo?: number; duration_hi?: number }): string {
  const lo = p.duration_lo ?? p.duration;
  const hi = p.duration_hi ?? p.duration;
  return lo === hi ? `≈ ${duration(p.duration)}` : `${lo}–${hi} min`;
}

/** "2026-11-14" + offset days -> Date at local noon (no timezone drift) */
export function tripDate(start: string, offset = 0): Date {
  const [y, m, d] = start.split("-").map(Number);
  return new Date(y, m - 1, d + offset, 12);
}

export const fmtDate = (d: Date, opts: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-GB", opts);

/** "14–16 Nov 2026", "30 Nov – 2 Dec 2026" */
export function dateRange(start: string | null, end: string | null): string {
  if (!start) return "No date yet";
  const a = tripDate(start);
  const b = tripDate(end ?? start);
  const full = { day: "numeric", month: "short", year: "numeric" } as const;
  if (start === (end ?? start)) return fmtDate(a, full);
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()) return `${a.getDate()}–${fmtDate(b, full)}`;
  return `${fmtDate(a, { day: "numeric", month: "short" })} – ${fmtDate(b, full)}`;
}
