"use client";

import { cx } from "@/components/ui";
import type { Place } from "@/lib/types";
import s from "./app.module.css";

/** Figma component "Place Row" (5:141): check · category / ward · score S_i */
export function PlaceRow({
  place,
  selected,
  hovered,
  onToggle,
  onHover,
}: {
  place: Place;
  selected: boolean;
  hovered?: boolean;
  onToggle: () => void;
  onHover?: (id: number | null) => void;
}) {
  return (
    <button
      type="button"
      className={s.placeRow}
      data-hover={hovered || undefined}
      aria-pressed={selected}
      onClick={onToggle}
      onMouseEnter={() => onHover?.(place.id)}
      onMouseLeave={() => onHover?.(null)}
      onFocus={() => onHover?.(place.id)}
      onBlur={() => onHover?.(null)}
    >
      <span className={cx(s.check, selected && s.checkOn)} aria-hidden>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {selected && <img src="/figma/checkmark.svg" width={12} height={12} alt="" />}
      </span>
      <span className={s.info}>
        <span className={s.name}>{place.label}</span>
        <span className={s.sub}>{place.ward}</span>
      </span>
      <span className={cx(s.score, selected && s.scoreOn)} title="Experience score S_i (estimated)">
        {place.score}
      </span>
    </button>
  );
}
