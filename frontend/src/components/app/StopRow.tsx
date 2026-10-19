"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { CSSProperties } from "react";
import { cx, DAY_COLORS } from "@/components/ui";
import { clock, duration } from "@/lib/time";
import type { Stop } from "@/lib/types";
import s from "./app.module.css";

/** Figma component "Stop" (5:149): time · rail · name / meta (golden hour, lock) */
export function StopRow({
  stop,
  day,
  last,
  onLockToggle,
  onHover,
}: {
  stop: Stop;
  day: number;
  last: boolean;
  onLockToggle: () => void;
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
      className={cx(s.stop, isDragging && s.stopDragging)}
      onMouseEnter={() => onHover(p.id)}
      onMouseLeave={() => onHover(null)}
      data-stop-id={p.id}
    >
      <span className={s.time}>{clock(stop.start)}</span>
      <span className={cx(s.rail, last && s.railLast)} aria-hidden />
      <div className={s.body}>
        <div className={s.titleRow}>
          <span className={s.title}>
            {p.label} · {p.ward}
          </span>
          <button
            type="button"
            className={cx(s.iconButton, stop.locked && s.iconOn)}
            onClick={onLockToggle}
            aria-pressed={stop.locked}
            title={stop.locked ? `Pinned to day ${day + 1} at ${clock(stop.locked_start ?? stop.start)} — click to unpin` : "Pin this day and time (booked)"}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/figma/lock.svg" width={14} height={14} alt={stop.locked ? "Pinned" : "Pin"} />
          </button>
        </div>
        <div className={s.meta}>
          <span>
            {duration(stop.depart - stop.start)}
            {stop.locked ? " · booked" : ""}
          </span>
          {stop.golden && (
            <span className={s.golden}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/figma/sun.svg" width={14} height={14} alt="" />
              Golden hour
            </span>
          )}
          {stop.wait > 5 && <span>waits {duration(stop.wait)}</span>}
          {stop.late_by > 0 && <span className={s.warn}>closes {stop.late_by} min early</span>}
        </div>
      </div>
      <button
        type="button"
        ref={setActivatorNodeRef}
        className={s.handle}
        aria-label={`Move ${p.label}`}
        {...attributes}
        {...listeners}
      >
        <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden>
          {[2, 8, 14].map((y) => (
            <g key={y}>
              <circle cx="2" cy={y} r="1.5" />
              <circle cx="8" cy={y} r="1.5" />
            </g>
          ))}
        </svg>
      </button>
    </div>
  );
}

export function Between({ travel, meal }: { travel: number; meal: number }) {
  if (!meal && travel < 1) return null;
  return (
    <div className={s.between}>
      <span className={s.betweenSpacer} />
      <span className={s.betweenRail} />
      <span>
        {meal > 0 ? (
          <span className={s.mealChip}>🍜 Meal break · {duration(meal)}</span>
        ) : (
          <span>{duration(travel)} travel</span>
        )}
      </span>
    </div>
  );
}
