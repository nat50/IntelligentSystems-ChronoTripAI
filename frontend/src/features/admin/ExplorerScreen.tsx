"use client";

import { useCallback, useEffect, useState } from "react";
import { interestLabel } from "@/components/app/PlaceRow";
import { CitySelect } from "@/components/app/TopBar";
import { ButtonLink, CONF_TONE, confLabel, cx, Pill, type Tone } from "@/components/ui";
import { Bars } from "@/components/ui/charts";
import { api } from "@/lib/api";
import { closedText, timeRange } from "@/lib/time";
import type { PlaceDetail, PlaceQuality } from "@/lib/types";
import { inWindow } from "../places/PlaceDetailPanel";
import { fmt, useAdmin, useAdminData } from "./admin-store";
import { Shell, Stat } from "./Shell";
import s from "./admin.module.css";

const QUALITY: Record<PlaceQuality, [Tone, string, string]> = {
  good: ["ok", "Good", "No open issues"],
  low_data: ["warn", "Low data", "Fewer than 10 check-ins: estimates lean on similar places"],
  missing_hours: ["bad", "Missing hours", "No crawled opening hours and an unstable estimate"],
};
const FILTERS: { key: PlaceQuality | ""; label: string }[] = [
  { key: "", label: "All" },
  { key: "low_data", label: "Low data" },
  { key: "missing_hours", label: "Missing hours" },
];
const HOURS = Array.from({ length: 17 }, (_, i) => i + 6);

/** Median visit length from the 20-min histogram (bin midpoint) */
function histMedian(hist: number[], edges: number[]): number | null {
  const total = hist.reduce((a, b) => a + b, 0);
  if (!total) return null;
  let acc = 0;
  for (let i = 0; i < hist.length; i++) {
    acc += hist[i];
    if (acc >= total / 2) return (edges[i] ?? i * 20) + 10;
  }
  return null;
}

function Detail({ p }: { p: PlaceDetail }) {
  const [tone, label, note] = QUALITY[p.quality];
  const edges = p.visit_hist.map((_, i) => i * 20); // [0, 20, …, 240]: lower edge of each bin
  const median = histMedian(p.visit_hist, edges);
  const durBin = Math.min(p.visit_hist.length - 1, Math.floor(p.duration / 20));
  const crawled = p.hours_source === "crawl";
  return (
    <>
      <div className={s.head}>
        <div>
          <h1 className={s.h1}>
            {p.label} · {p.ward} <Pill small>{interestLabel(p)}</Pill>
          </h1>
          <p className={s.sub}>
            ID {p.venue || p.id} · {p.lat.toFixed(3)}, {p.lon.toFixed(3)} · opening hours {crawled ? "from web crawl (OpenStreetMap)" : "estimated from check-ins"}
          </p>
        </div>
        <ButtonLink href={`/plan/places?place=${p.id}`} variant="outline">
          Open in traveler view
        </ButtonLink>
      </div>
      <div className={s.stats4}>
        <Stat label="Check-ins" value={fmt(p.n_checkins)} note="2012–2014" />
        <Stat label="Unique users" value={fmt(p.n_users)} note={`${Math.round(p.one_time_share * 100)}% one-time visitors`} />
        <Stat label="Opening hours" value={timeRange(p.open_min, p.close_min)} note={crawled ? closedText(p.closed_days) || "Open every day" : "Estimated"} />
        <Stat label="Data quality" value={<span data-q={tone}>{label}</span>} note={note} />
      </div>
      <div className={s.grid2}>
        <section className={s.card}>
          <h2 className={s.h3}>Check-ins by hour</h2>
          <p className={s.sub}>Input of M2 (hour profile) · local time</p>
          <Bars
            label="Check-ins by hour"
            color="var(--admin)"
            height={110}
            values={HOURS.map((h) => p.hour_profile[h] ?? 0)}
            on={(i) => inWindow(HOURS[i], p.golden_start, p.golden_end)}
            ticks={["06:00", "10:00", "14:00", "18:00", "22:00"]}
          />
          <p className={s.note}>
            Blue = best time predicted by M2 ({timeRange(p.golden_start, p.golden_end)}): open and below the daily peak.
          </p>
        </section>
        <section className={s.card}>
          <h2 className={s.h3}>Visit length</h2>
          <p className={s.sub}>Input of M3 (visit length) · minutes per visit · {fmt(p.n_visits)} measured visits</p>
          {p.visit_hist.length ? (
            <Bars label="Visit length" color="var(--admin)" height={110} values={p.visit_hist} on={(i) => i === durBin} ticks={["0", "60", "120", "180", "240+"]} />
          ) : (
            <p className={s.muted}>No measured visits for this place.</p>
          )}
          <p className={s.note}>
            {median != null ? `Median ≈ ${median} min · ` : ""}current M3 estimate {p.duration} min.
          </p>
        </section>
      </div>
      <section className={s.card}>
        <div className={s.cardHead}>
          <h2 className={s.h3}>Current model outputs for this place (active versions)</h2>
          <span className={s.pink}>Shown to travelers in T2</span>
        </div>
        <div className={s.tableWrap}>
          <table className={s.table}>
            <thead>
              <tr>
                <th>Model</th>
                <th>Output</th>
                <th>Version</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["m1", "M1 · Popularity", `${p.score} / 100`, p.conf_m1],
                  ["m2", "M2 · Hour profile", `Best ${timeRange(p.golden_start, p.golden_end)}`, p.conf_m2],
                  ["m3", "M3 · Visit length", `≈ ${p.duration} min`, p.conf_m3],
                ] as const
              ).map(([k, name, out, conf]) => (
                <tr key={k}>
                  <td className={s.strong}>{name}</td>
                  <td>{out}</td>
                  <td>{p.model_versions[k] ?? "—"}</td>
                  <td>
                    {conf && (
                      <Pill small tone={CONF_TONE[conf]}>
                        {confLabel(conf)}
                      </Pill>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/** Figma D2 · Place explorer (84:361) */
export function ExplorerScreen() {
  const { call } = useAdmin();
  const [cities] = useAdminData(useCallback(() => api.cities(), []));
  const [city, setCity] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [quality, setQuality] = useState<PlaceQuality | "">("");
  const [page, setPage] = useState<Awaited<ReturnType<typeof api.explorer>> | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<PlaceDetail | null>(null);

  // deep links from D1 (?quality=) and D3 largest errors (?q=)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const want = params.get("quality");
    /* eslint-disable react-hooks/set-state-in-effect -- one-time read of the URL */
    if (want === "low_data" || want === "missing_hours") setQuality(want);
    setQ(params.get("q") ?? "");
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const current = city ?? cities?.[0]?.name ?? null;

  useEffect(() => {
    if (!current) return;
    const id = setTimeout(() => {
      void call(() => api.explorer({ city: current, q: q.trim(), quality: quality || undefined, limit: 100 })).then((r) => {
        if (!r) return;
        setPage(r);
        setSelected((sel) => (r.places.some((x) => x.id === sel) ? sel : (r.places[0]?.id ?? null)));
      });
    }, 250);
    return () => clearTimeout(id);
  }, [current, q, quality, call]);

  useEffect(() => {
    if (selected == null) return;
    let alive = true;
    void call(() => api.place(selected)).then((p) => alive && p && setDetail(p));
    return () => {
      alive = false;
    };
  }, [selected, call]);

  return (
    <Shell active="/admin/places">
      <div className={s.explorer}>
        <aside className={s.listPanel}>
          <div>
            <h1 className={s.h1}>Places</h1>
            <p className={s.sub}>
              {current && cities ? (
                <CitySelect value={current} options={cities.map((c) => c.name)} onChange={setCity} />
              ) : (
                "—"
              )}{" "}
              · {fmt(page?.total)} places
            </p>
          </div>
          <label className={s.search}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input type="search" placeholder="Search by name or ID" aria-label="Search by name or ID" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <div className={s.chips}>
            {FILTERS.map((f) => (
              <button key={f.key} type="button" aria-pressed={quality === f.key} className={cx(s.chip, quality === f.key && s.chipOn)} onClick={() => setQuality(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <div className={s.placeList} data-lenis-prevent>
            {page?.places.map((x) => {
              const [tone, label] = QUALITY[x.quality];
              return (
                <button key={x.id} type="button" className={cx(s.placeItem, x.id === selected && s.placeItemOn)} aria-current={x.id === selected || undefined} onClick={() => setSelected(x.id)}>
                  <span>
                    <strong>{x.name}</strong>
                    <span>{fmt(x.n_checkins)} check-ins</span>
                  </span>
                  <Pill small tone={tone}>
                    {label}
                  </Pill>
                </button>
              );
            })}
            {page && page.places.length === 0 && <p className={s.muted}>No place matches.</p>}
          </div>
        </aside>
        <main className={s.detailMain}>{detail ? <Detail p={detail} /> : <p className={s.muted}>Select a place.</p>}</main>
      </div>
    </Shell>
  );
}
