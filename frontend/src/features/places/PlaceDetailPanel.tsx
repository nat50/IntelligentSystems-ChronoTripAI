"use client";

import { useEffect, useState } from "react";
import { interestLabel } from "@/components/app/PlaceRow";
import { Button, confLabel, Pill } from "@/components/ui";
import { Bars } from "@/components/ui/charts";
import { api } from "@/lib/api";
import { durationRange, hoursText, timeRange } from "@/lib/time";
import type { Confidence, PlaceDetail } from "@/lib/types";
import s from "../screen.module.css";

const HOURS = Array.from({ length: 17 }, (_, i) => i + 6); // 06 … 22, as in Figma

/** The hours a window [start, end) in minutes touches, e.g. 09:00–11:00 -> 9, 10 */
export const inWindow = (h: number, start: number, end: number) => h * 60 + 60 > start && h * 60 < end;

/** "v3" when every model comes from one version, else "M1 v3 · M2 v3 · M3 v5" */
export function versionText(v: Record<string, string>) {
  const values = [...new Set(Object.values(v))];
  if (values.length <= 1) return values[0] ?? "—";
  return ["m1", "m2", "m3"].map((k) => `${k.toUpperCase()} ${v[k] ?? "—"}`).join(" · ");
}

function ModelCard({ label, value, model, conf }: { label: string; value: string; model: string; conf?: Confidence }) {
  return (
    <div className={s.modelCard}>
      <div>
        <span className={s.modelCardLabel}>{label}</span>
        <span className={s.modelCardValue}>{value}</span>
      </div>
      <span className={s.modelCardSide}>
        <span className={s.modelTag}>Model {model}</span>
        {conf && <span className={s.confText}>{confLabel(conf)} confidence</span>}
      </span>
    </div>
  );
}

export function PlaceDetailPanel({
  id,
  selected,
  must,
  full,
  onToggle,
  onMust,
  onClose,
}: {
  id: number;
  selected: boolean;
  must: boolean;
  full: boolean;
  onToggle: (p: PlaceDetail) => void;
  onMust: (p: PlaceDetail, on: boolean) => void;
  onClose: () => void;
}) {
  const [place, setPlace] = useState<PlaceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .place(id)
      .then((p) => {
        if (!alive) return;
        setPlace(p);
        setError(null);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [id]);

  const p = place?.id === id ? place : null;

  return (
    <aside className={s.detail} aria-label="Place details" data-lenis-prevent>
      <div className={s.detailHead}>
        {p ? <Pill small>{interestLabel(p)}</Pill> : <span />}
        <button type="button" className={s.close} onClick={onClose} aria-label="Close details">
          ×
        </button>
      </div>
      {error && <p className={s.error}>{error}</p>}
      {p && (
        <>
          <div>
            <h2 className={s.detailTitle}>
              {p.label} · {p.ward}
            </h2>
            <p className={s.sub}>{hoursText(p)}</p>
          </div>
          <div className={s.modelCards}>
            <ModelCard label="Popularity" value={`${p.score} / 100`} model="M1" conf={p.conf_m1} />
            <ModelCard label="Best time to visit" value={timeRange(p.golden_start, p.golden_end).replace("–", " – ")} model="M2" conf={p.conf_m2} />
            <ModelCard label="Typical visit length" value={durationRange(p)} model="M3" conf={p.conf_m3} />
          </div>
          <div className={s.chartBlock}>
            <p className={s.chartTitle}>
              Check-ins by hour · <span className={s.pinkText}>pink</span> = best time (open, fewer crowds)
            </p>
            <Bars
              label="Check-ins by hour"
              values={HOURS.map((h) => p.hour_profile[h] ?? 0)}
              on={(i) => inWindow(HOURS[i], p.golden_start, p.golden_end)}
              ticks={["06", "10", "14", "18", "22"]}
            />
          </div>
          <p className={s.notice}>
            Estimated by model version {versionText(p.model_versions)}. Values may differ on public holidays.
          </p>
          <div className={s.detailActions}>
            <Button variant="outline" onClick={() => onToggle(p)} disabled={!selected && full}>
              {selected ? "Remove" : "Add to trip"}
            </Button>
            <Button onClick={() => onMust(p, !must)} disabled={!selected && !must && full}>
              {must ? "✓ Must-visit" : "Mark as must-visit"}
            </Button>
          </div>
        </>
      )}
    </aside>
  );
}
