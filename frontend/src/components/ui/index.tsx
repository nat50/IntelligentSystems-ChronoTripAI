import Link from "next/link";
import type { ButtonHTMLAttributes, CSSProperties, ReactNode } from "react";
import type { Confidence } from "@/lib/types";
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

type Variant = "primary" | "outline" | "ghost" | "admin";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
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
  variant?: Variant;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Link href={href} className={cx(s.button, s[variant], className)}>
      {children}
    </Link>
  );
}

/** step: "1" shows "1 Trip setup"; done shows "✓ Trip setup" (Figma planner steps) */
export interface NavItem {
  href: string;
  label: string;
  disabled?: boolean;
  step?: string;
  done?: boolean;
}

export function Segmented({
  items,
  active,
}: {
  items: NavItem[];
  active: string;
}) {
  return (
    <nav className={s.segmented} aria-label="Sections">
      {items.map((it) => {
        const label = it.done && it.href !== active ? `✓ ${it.label}` : it.step ? `${it.step} ${it.label}` : it.label;
        return it.disabled ? (
          <span key={it.href} aria-disabled="true" className={cx(s.segment, s.segmentDisabled)}>
            {label}
          </span>
        ) : (
          <Link key={it.href} href={it.href} aria-current={it.href === active ? "page" : undefined} className={cx(s.segment, it.href === active && s.segmentActive)}>
            {label}
          </Link>
        );
      })}
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

export type Tone = "ok" | "warn" | "bad" | "neutral" | "accent" | "admin";

const TONE: Record<Tone, string> = {
  ok: s.pillOk,
  warn: s.pillWarn,
  bad: s.pillBad,
  neutral: s.pillNeutral,
  accent: s.pillAccent,
  admin: s.pillAdmin,
};

/** Figma "Tag" / status pill */
export function Pill({ tone = "neutral", small, children }: { tone?: Tone; small?: boolean; children: ReactNode }) {
  return <span className={cx(s.pill, TONE[tone], small && s.pillSmall)}>{children}</span>;
}

export const CONF_TONE: Record<Confidence, Tone> = { high: "ok", medium: "warn", low: "neutral" };
export const confLabel = (c: Confidence) => c[0].toUpperCase() + c.slice(1);

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
  tone = "accent",
}: {
  checked: boolean;
  onChange: (on: boolean) => void;
  label: string;
  disabled?: boolean;
  tone?: "accent" | "admin";
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={cx(s.toggle, checked && s.toggleOn, tone === "admin" && s.toggleAdmin)}
      onClick={() => onChange(!checked)}
    />
  );
}

/** Labelled form field (Figma inputs: 13px label above a 46px box) */
export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx(s.field, className)}>
      <span className={s.fieldLabel}>{label}</span>
      {children}
      {hint && <span className={s.fieldHint}>{hint}</span>}
    </label>
  );
}

export const inputClass = s.input;

/** Centered dialog over a dimmed backdrop; Escape closes it when onClose is given */
export function Modal({ title, icon, onClose, children, labelledBy = "modal-title" }: { title: ReactNode; icon?: ReactNode; onClose?: () => void; children: ReactNode; labelledBy?: string }) {
  return (
    <div
      className={s.backdrop}
      onKeyDown={(e) => e.key === "Escape" && onClose?.()}
      onClick={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div className={s.modal} role="dialog" aria-modal="true" aria-labelledby={labelledBy} tabIndex={-1} autoFocus>
        <h2 id={labelledBy} className={s.modalTitle}>
          {icon}
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
