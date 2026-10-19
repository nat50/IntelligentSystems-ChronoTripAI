import Link from "next/link";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import type { Confidence, ModelState } from "@/lib/types";
import s from "./ui.module.css";

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");

export const DAY_COLORS = ["var(--day-1)", "var(--day-2)", "var(--day-3)"];

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className={s.logo} aria-label="ChronoTrip home">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/figma/logo-dot.svg" width={14} height={14} alt="" />
      ChronoTrip
    </Link>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost";
  block?: boolean;
  loading?: boolean;
};

export function Button({ variant = "primary", block, loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      className={cx(s.button, s[variant], block && s.block, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <span className={s.spinner} aria-hidden />}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  className,
  children,
}: {
  href: string;
  variant?: "primary" | "outline" | "ghost";
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={cx(s.button, s[variant], className)}>
      {children}
    </Link>
  );
}

export function Segmented({
  items,
  active,
}: {
  items: { href: string; label: string; disabled?: boolean }[];
  active: string;
}) {
  return (
    <nav className={s.segmented} aria-label="Sections">
      {items.map((it) => (
        it.disabled ? (
          <span key={it.href} aria-disabled="true" className={cx(s.segment, s.segmentDisabled)}>
            {it.label}
          </span>
        ) : (
          <Link key={it.href} href={it.href} aria-current={it.href === active ? "page" : undefined} className={cx(s.segment, it.href === active && s.segmentActive)}>
            {it.label}
          </Link>
        )
      ))}
    </nav>
  );
}

export function DayPicker({
  count,
  value,
  onChange,
  colored = false,
  total = 3,
  dropTarget,
  dayRef,
}: {
  count?: number;
  value: number; // 0-based
  onChange: (day: number) => void;
  colored?: boolean;
  total?: number;
  dropTarget?: number | null;
  dayRef?: (day: number) => (el: HTMLButtonElement | null) => void;
}) {
  const n = count ?? total;
  return (
    <div className={s.days} role="tablist" aria-label="Day">
      {Array.from({ length: n }, (_, d) => (
        <button
          key={d}
          ref={dayRef?.(d)}
          type="button"
          role="tab"
          aria-selected={d === value}
          className={cx(s.day, d === value && s.dayActive, dropTarget === d && s.dayDrop)}
          style={colored ? ({ "--day-color": DAY_COLORS[d] } as CSSProperties) : undefined}
          onClick={() => onChange(d)}
        >
          {d + 1}
        </button>
      ))}
    </div>
  );
}

export function Slider({
  value,
  onChange,
  label,
  min = 0,
  max = 1,
  step = 0.05,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <input
      type="range"
      className={s.slider}
      aria-label={label}
      min={min}
      max={max}
      step={step}
      value={value}
      style={{ "--pct": `${pct}%` } as CSSProperties}
      onChange={(e) => onChange(Number(e.target.value))}
    />
  );
}

const PILL: Record<ModelState | "active", [string, string]> = {
  trained: [s.pillOk, "Trained"],
  training: [s.pillWarn, "Training"],
  queued: [s.pillNeutral, "Queued"],
  failed: [s.pillBad, "Failed"],
  active: [s.pillAccent, "Active"],
};

export function StatusPill({ state }: { state: ModelState | "active" }) {
  const [cls, label] = PILL[state];
  return (
    <span className={cx(s.pill, cls)}>
      {state === "training" && <span className={s.pulse} aria-hidden />}
      {label}
    </span>
  );
}

const CONF_COLOR: Record<Confidence, string> = { high: "var(--ok)", medium: "var(--golden)", low: "var(--pin-idle)" };

export function Estimated({ confidence }: { confidence?: Confidence }) {
  return (
    <span className={s.estimated} title="Predicted from check-ins, not official data">
      {confidence && <span className={s.confDot} style={{ background: CONF_COLOR[confidence] }} aria-hidden />}
      Estimated{confidence ? ` · ${confidence} confidence` : ""}
    </span>
  );
}
