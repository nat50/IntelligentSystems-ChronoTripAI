"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { CSSProperties } from "react";
import { cx, DAY_COLORS } from "@/components/ui";
import { clock, duration } from "@/lib/time";
import type { Stop } from "@/lib/types";
import s from "./app.module.css";

/** "60 min · golden hour" / "50 min · moved by you" / "60 min · booked, time kept" */
function StopMeta({ stop, moved }: { stop: Stop; moved?: boolean }) {
  const len = duration(stop.depart - stop.start);
  return (
    <span className={s.meta}>
      {moved ? (
        <span>{len} · moved by you</span>
      ) : stop.locked ? (
        <span>{len} · booked, time kept</span>
      ) : stop.golden ? (
        <span className={s.golden}>{len} · golden hour</span>
      ) : (
        <span>{len}</span>
      )}
      {stop.wait > 5 && <span>waits {duration(stop.wait)}</span>}
      {stop.late_by > 0 && <span className={s.warn}>closes {stop.late_by} min early</span>}
    </span>
  );
}

/** Read-only stop (shared trip page, print) */
export function StopLine({ stop, day }: { stop: Stop; day: number }) {
  const p = stop.place;
  return (
    <div className={s.stop} style={{ "--day-color": DAY_COLORS[day] } as CSSProperties}>
      <span className={s.time}>{clock(stop.start)}</span>
      <span className={s.dot} aria-hidden />
      <div className={s.body}>
        <span className={s.title}>
          {p.label} · {p.ward}
        </span>
        <StopMeta stop={stop} />
      </div>
    </div>
  );
}

/** Figma T3 stop: handle · time · dot · name / meta · lock · remove */
export function StopRow({
  stop,
  day,
  moved,
  onLockToggle,
  onRemove,
  onHover,
}: {
  stop: Stop;
  day: number;
  moved?: boolean;
  onLockToggle: () => void;
  onRemove: () => void;
  onHover: (id: number | null) => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: stop.place.id,
  });
  const style: CSSProperties = {
    transform: CSS.Translate.toString(transform),
    transition,
    "--day-color": DAY_COLORS[day],
  } as CSSProperties;
  const p = stop.place;
  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cx(s.stop, s.stopEditable, isDragging && s.stopDragging, moved && s.stopMoved)}
      onMouseEnter={() => onHover(p.id)}
      onMouseLeave={() => onHover(null)}
      data-stop-id={p.id}
    >
      <button type="button" ref={setActivatorNodeRef} className={s.handle} aria-label={`Move ${p.label}`} {...attributes} {...listeners}>
        <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden>
          {[2, 8, 14].map((y) => (
            <g key={y}>
              <circle cx="2" cy={y} r="1.5" />
              <circle cx="8" cy={y} r="1.5" />
            </g>
          ))}
        </svg>
      </button>
      <span className={s.time}>{clock(stop.start)}</span>
      <span className={s.dot} aria-hidden />
      <div className={s.body}>
        <span className={s.title}>
          {p.label} · {p.ward}
        </span>
        <StopMeta stop={stop} moved={moved} />
      </div>
      <button
        type="button"
        className={cx(s.iconButton, stop.locked && s.iconOn)}
        onClick={onLockToggle}
        aria-pressed={stop.locked}
        title={stop.locked ? `Locked to day ${day + 1} at ${clock(stop.locked_start ?? stop.start)} — click to unlock` : "Lock this day and time (booked)"}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill={stop.locked ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" aria-hidden>
          <rect x="4" y="11" width="16" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" fill="none" />
        </svg>
        <span className="visually-hidden">{stop.locked ? "Unlock" : "Lock"}</span>
      </button>
      <button type="button" className={s.iconButton} onClick={onRemove} aria-label={`Remove ${p.label} from the trip`}>
        <svg width="14" height="14" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>
    </div>
  );
}

export function Between({ travel, meal }: { travel: number; meal: number }) {
  if (!meal && travel < 1) return null;
  return (
    <div className={s.between}>
      {meal > 0 ? (
        <span className={s.mealChip}>🍜 Meal break · {duration(meal)}</span>
      ) : (
        <span className={s.ride}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M5 17h14M6 17l1.5-6h9L18 17M7 17v2M17 17v2" />
          </svg>
          {duration(travel)} by car
        </span>
      )}
    </div>
  );
}
