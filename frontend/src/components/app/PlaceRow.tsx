"use client";

import { cx } from "@/components/ui";
import { INTERESTS } from "@/lib/trip-store";
import type { Place } from "@/lib/types";
import s from "./app.module.css";

export const interestLabel = (p: Place) => INTERESTS.find((i) => i.key === p.interest)?.label ?? p.group;

/** Figma T2 place row: check · name (+ Must-visit) / ward · interest · score S_i */
export function PlaceRow({
  place,
  selected,
  must,
  active,
  hovered,
  onToggle,
  onOpen,
  onHover,
}: {
  place: Place;
  selected: boolean;
  must?: boolean;
  active?: boolean;
  hovered?: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onHover?: (id: number | null) => void;
}) {
  return (
    <div
      className={cx(s.placeRow, active && s.placeRowActive)}
      data-hover={hovered || undefined}
      onMouseEnter={() => onHover?.(place.id)}
      onMouseLeave={() => onHover?.(null)}
    >
      <button
        type="button"
        className={cx(s.check, selected && s.checkOn)}
        role="checkbox"
        aria-checked={selected}
        aria-label={`${selected ? "Remove" : "Add"} ${place.label} · ${place.ward}`}
        onClick={onToggle}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {selected && <img src="/figma/checkmark.svg" width={12} height={12} alt="" />}
      </button>
      <button type="button" className={s.rowMain} onClick={onOpen} aria-expanded={active} onFocus={() => onHover?.(place.id)} onBlur={() => onHover?.(null)}>
        <span className={s.info}>
          <span className={s.nameLine}>
            <span className={s.name}>{place.label}</span>
            {must && <span className={s.mustTag}>Must-visit</span>}
          </span>
          <span className={s.sub}>
            {place.ward} · {interestLabel(place)}
          </span>
        </span>
        <span className={cx(s.score, selected && s.scoreOn)} title="Popularity (model M1, estimated)">
          {place.score}
        </span>
      </button>
    </div>
  );
}
