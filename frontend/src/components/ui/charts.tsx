import type { CSSProperties } from "react";
import s from "./ui.module.css";

/**
 * Small hand-rolled charts for T2, D2, D3, D4 (no chart dependency).
 * Bars: one value per bar, `on` bars use the highlight colour.
 */
export function Bars({
  values,
  on,
  color = "var(--accent)",
  ticks,
  label,
  height = 80,
}: {
  values: number[];
  on?: (i: number) => boolean;
  color?: string;
  ticks?: string[];
  label: string;
  height?: number;
}) {
  const max = Math.max(...values, 1e-9);
  return (
    <figure className={s.chart} aria-label={label}>
      <div className={s.bars} style={{ height } as CSSProperties}>
        {values.map((v, i) => (
          <span
            key={i}
            className={s.barCol}
            style={{ height: `${Math.max(3, (100 * v) / max)}%`, background: on?.(i) ? color : undefined }}
          />
        ))}
      </div>
      {ticks && (
        <div className={s.ticks}>
          {ticks.map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
      )}
    </figure>
  );
}

export interface Series {
  values: number[];
  color: string;
  dashed?: boolean;
  label: string;
}

/** Line chart over a shared x index; y scaled to the min..max of all series */
export function Lines({ series, ticks, label, height = 120 }: { series: Series[]; ticks?: string[]; label: string; height?: number }) {
  const all = series.flatMap((x) => x.values).filter(Number.isFinite);
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const n = Math.max(...series.map((x) => x.values.length), 2);
  const pts = (v: number[]) => v.map((y, i) => `${(100 * i) / (n - 1)},${100 - 8 - (84 * (y - lo)) / span}`).join(" ");
  return (
    <figure className={s.chart} aria-label={label}>
      <svg className={s.lines} viewBox="0 0 100 100" preserveAspectRatio="none" style={{ height }} role="img" aria-label={label}>
        {[25, 50, 75].map((y) => (
          <line key={y} x1="0" x2="100" y1={y} y2={y} className={s.grid} />
        ))}
        {series.map((x) => (
          <polyline
            key={x.label}
            points={pts(x.values)}
            fill="none"
            stroke={x.color}
            strokeWidth="2"
            strokeDasharray={x.dashed ? "5 4" : undefined}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      {ticks && (
        <div className={s.ticks}>
          {ticks.map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
      )}
      <figcaption className={s.legend}>
        {series.map((x) => (
          <span key={x.label}>
            <i style={{ background: x.color, opacity: x.dashed ? 0.6 : 1 }} aria-hidden />
            {x.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
