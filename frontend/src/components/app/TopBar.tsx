import type { ReactNode } from "react";
import { Logo, Segmented, type NavItem } from "@/components/ui";
import s from "./app.module.css";

export function TopBar({
  items,
  active,
  right,
  badge,
}: {
  items: NavItem[];
  active: string;
  right?: ReactNode;
  badge?: ReactNode;
}) {
  return (
    <header className={s.topbar}>
      <span className={s.brand}>
        <Logo />
        {badge}
      </span>
      <Segmented items={items} active={active} />
      <div className={s.topRight}>{right}</div>
    </header>
  );
}

export function CitySelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (city: string) => void;
}) {
  return (
    <select className={s.citySelect} value={value} onChange={(e) => onChange(e.target.value)} aria-label="City">
      {(options.length ? options : [value]).map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}
