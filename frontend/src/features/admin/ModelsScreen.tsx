"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Button, cx, inputClass, Pill, type Tone } from "@/components/ui";
import { Lines } from "@/components/ui/charts";
import { api } from "@/lib/api";
import type { Impact, ModelCard, ModelDetail, ModelKey, ModelVersionRow } from "@/lib/types";
import { fmtDay, fmtStamp, pollJob, useAdmin, useAdminData } from "./admin-store";
import { Shell, Stat } from "./Shell";
import s from "./admin.module.css";

// allowed ranges, mirrored from backend/ml/models.py SETTINGS (the API rejects others with 422)
const RANGES: Record<ModelKey, Record<string, [number, number, number]>> = {
  m1: { learning_rate: [0.005, 0.5, 0.005], num_leaves: [7, 255, 1], n_cutoffs: [1, 8, 1] },
  m2: { quiet_floor: [0, 0.9, 0.05], window_mass: [0.5, 0.99, 0.01] },
  m3: { learning_rate: [0.005, 0.5, 0.005], num_leaves: [7, 255, 1] },
};
const ALGORITHM: Record<ModelKey, string> = {
  m1: "LightGBM ranking",
  m2: "Dirichlet–Multinomial",
  m3: "Quantile boosting",
};

type Metric = { label: string; get: (m: Record<string, unknown>) => number | null | undefined; unit: string; higher: boolean; pct?: boolean };
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const METRICS: Record<ModelKey, Metric[]> = {
  m1: [
    { label: "Spearman (test)", get: (m) => num(m.spearman_all) ?? num(m.spearman), unit: "", higher: true },
    { label: "NDCG@20", get: (m) => num(m.ndcg20), unit: "", higher: true },
    { label: "Raw-count baseline", get: (m) => num(m.spearman_all_baseline) ?? num(m.spearman_baseline), unit: "", higher: true },
  ],
  m2: [
    { label: "Log-likelihood", get: (m) => num(m.loglik), unit: "", higher: true },
    { label: "Opening time error", get: (m) => num((m.hours_eval as { open_mae_min?: number } | undefined)?.open_mae_min), unit: "min", higher: false },
    { label: "Closing time error", get: (m) => num((m.hours_eval as { close_mae_min?: number } | undefined)?.close_mae_min), unit: "min", higher: false },
  ],
  m3: [
    { label: "MAE (mean absolute error)", get: (m) => num(m.mae), unit: "min", higher: false },
    { label: "RMSE", get: (m) => num(m.rmse), unit: "min", higher: false },
    { label: "Within ±15 min", get: (m) => num(m.within_15), unit: "%", higher: true, pct: true },
  ],
};

const show = (v: number | null | undefined, m: Pick<Metric, "unit" | "pct">) =>
  v == null ? "—" : m.pct ? `${Math.round(v * 100)}%` : m.unit ? `${v.toFixed(1)} ${m.unit}` : v.toFixed(3);

const STATUS: Record<ModelCard["status"], (c: ModelCard) => [Tone, string]> = {
  active: (c) => ["ok", `Active ${c.active_version ?? ""}`],
  training: (c) => ["admin", `Training${c.progress != null ? ` · ${Math.round(c.progress * 100)}%` : ""}`],
  new_run_ready: () => ["warn", "New run ready"],
  failed: () => ["bad", "Last run failed"],
  untrained: () => ["neutral", "Not trained"],
};

function better(row: ModelVersionRow, active: ModelVersionRow | undefined) {
  const a = active?.headline.value;
  const b = row.headline.value;
  if (a == null || b == null) return null;
  return row.headline.higher_is_better ? b > a : b < a;
}

/** Figma D3 · Models (85:241) */
export function ModelsScreen() {
  const { call } = useAdmin();
  const [cards, reloadCards] = useAdminData(useCallback(() => api.models(), []));
  const [pick, setPick] = useState<ModelKey | null>(null);
  const [detail, setDetail] = useState<ModelDetail | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  const [editing, setEditing] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const key: ModelKey = pick ?? cards?.find((c) => c.status === "new_run_ready")?.key ?? "m3";
  const card = cards?.find((c) => c.key === key);

  const loadDetail = useCallback(async () => {
    const d = await call(() => api.model(key));
    if (!d) return;
    setDetail(d);
    setVersion((v) => (d.versions.some((x) => x.version === v) ? v : (d.versions[0]?.version ?? null)));
  }, [call, key]);

  useEffect(() => {
    const id = setTimeout(() => void loadDetail(), 0);
    return () => clearTimeout(id);
  }, [loadDetail]);

  // poll while a model trains
  const training = cards?.some((c) => c.status === "training");
  useEffect(() => {
    if (!training) return;
    const id = setInterval(() => void reloadCards(), 3000);
    return () => clearInterval(id);
  }, [training, reloadCards]);

  const rows = detail?.key === key ? detail.versions : [];
  const row = rows.find((r) => r.version === version);
  const activeRow = rows.find((r) => r.active) ?? rows.find((r) => r.origin === card?.active_version);

  useEffect(() => {
    if (!row || row.active) return;
    let alive = true;
    void call(() => api.impact(key, row.version)).then((x) => alive && setImpact(x ?? null));
    return () => {
      alive = false;
      setImpact(null);
    };
  }, [row, key, call]);

  const train = async () => {
    setBusy("train");
    const job = await call(() => api.trainModel(key, editing ?? card?.settings ?? {}));
    if (job) {
      setEditing(null);
      await reloadCards();
      const done = await call(() => pollJob(job, (j) => setStatus(`Training ${key.toUpperCase()} · ${j.message}`)));
      setStatus(done ? `Training ${done.status} · ${done.message}` : null);
      await Promise.all([reloadCards(), loadDetail()]);
    }
    setBusy(null);
  };

  const activate = async (v: string) => {
    setBusy(`activate:${v}`);
    const job = await call(() => api.activateModel(key, v));
    if (job) {
      const done = await call(() => pollJob(job, (j) => setStatus(`Activating ${v} · ${j.message}`)));
      setStatus(done ? `${v}: ${done.status} · ${done.message}` : null);
      await Promise.all([reloadCards(), loadDetail()]);
    }
    setBusy(null);
  };

  const shares = card?.split.shares ?? {};
  const split = ["train", "val", "test"].every((k) => shares[k] != null)
    ? `${["train", "val", "test"].map((k) => Math.round(shares[k] * 100)).join(" / ")} %`
    : "By time";
  const curve = row?.metrics.learning_curve;
  const errors = row?.metrics.largest_errors;
  const b = row && !row.active ? better(row, activeRow) : null;

  return (
    <Shell active="/admin/models">
      <div className={s.models}>
        <aside className={s.col}>
          <div>
            <h1 className={s.h1}>Models</h1>
            <p className={s.sub}>3 models · active version {cards?.find((c) => c.active_version)?.active_version ?? "—"}</p>
          </div>
          {cards?.map((c) => {
            const [tone, label] = STATUS[c.status](c);
            return (
              <button key={c.key} type="button" className={cx(s.modelItem, c.key === key && s.modelItemOn)} aria-current={c.key === key || undefined} onClick={() => setPick(c.key)}>
                <strong>{c.name}</strong>
                <span>{c.description}</span>
                <Pill small tone={tone}>
                  {label}
                </Pill>
                {c.status === "training" && (
                  <span className={s.bar}>
                    <span style={{ width: `${(c.progress ?? 0.5) * 100}%` }} />
                  </span>
                )}
              </button>
            );
          })}
        </aside>

        <main className={s.col}>
          <section className={s.card}>
            <div className={s.cardHead}>
              <div>
                <h2 className={s.h2}>{card?.name ?? key.toUpperCase()}</h2>
                <p className={s.sub}>{card?.description}</p>
              </div>
              <div className={s.headActions}>
                <Button variant="outline" onClick={() => setEditing(editing ? null : { ...(card?.settings ?? {}) })} aria-expanded={Boolean(editing)}>
                  {editing ? "Close settings" : "Edit settings"}
                </Button>
                <Button variant="admin" onClick={train} loading={busy === "train"} disabled={Boolean(busy) || card?.status === "training"}>
                  Start training
                </Button>
              </div>
            </div>
            <div className={s.grid3}>
              <label className={s.field}>
                <span>Dataset</span>
                <input className={inputClass} readOnly value={card?.active_version ?? "—"} />
              </label>
              <label className={s.field}>
                <span>Split (by time, fixed)</span>
                <input className={inputClass} readOnly value={split} title={card?.split.train_end ? `train until ${card.split.train_end}, validation until ${card.split.val_end}` : undefined} />
              </label>
              <label className={s.field}>
                <span>Algorithm</span>
                <input className={inputClass} readOnly value={ALGORITHM[key]} />
              </label>
            </div>
            {editing && (
              <div className={s.grid3}>
                {Object.entries(RANGES[key]).map(([name, [lo, hi, step]]) => (
                  <label key={name} className={s.field}>
                    <span>
                      {name.replace(/_/g, " ")} ({lo}–{hi})
                    </span>
                    <input
                      className={inputClass}
                      type="number"
                      min={lo}
                      max={hi}
                      step={step}
                      value={editing[name] ?? ""}
                      onChange={(e) => setEditing({ ...editing, [name]: Number(e.target.value) })}
                    />
                  </label>
                ))}
              </div>
            )}
            {status && (
              <p className={s.status} aria-live="polite">
                {status}
              </p>
            )}
          </section>

          <section className={cx(s.card, s.grow)}>
            {row ? (
              <>
                <div className={s.cardHead}>
                  <div>
                    <h2 className={s.h3}>
                      Run {row.version} · finished {fmtStamp(row.created_at)}
                    </h2>
                    <p className={s.sub}>Evaluated on the test period (Nov 2013 – Jan 2014), never used in training.</p>
                  </div>
                  {row.active ? (
                    <Pill small tone="ok">
                      Active
                    </Pill>
                  ) : (
                    b != null && (
                      <Pill small tone={b ? "ok" : "warn"}>
                        {b ? "Better" : "Worse"} than active {activeRow?.version}
                      </Pill>
                    )
                  )}
                </div>
                <div className={s.grid3}>
                  {METRICS[key].map((m) => {
                    const v = m.get(row.metrics);
                    const ref = row.active ? undefined : activeRow && m.get(activeRow.metrics);
                    const good = v != null && ref != null ? (m.higher ? v >= ref : v <= ref) : undefined;
                    return (
                      <Stat
                        key={m.label}
                        label={m.label}
                        value={show(v, m)}
                        tone={good === undefined ? undefined : good ? "ok" : "bad"}
                        note={ref != null && activeRow ? `${activeRow.version}: ${show(ref, m)}` : row.headline.baseline != null && m === METRICS[key][0] ? `baseline: ${show(row.headline.baseline, m)}` : undefined}
                      />
                    );
                  })}
                </div>
                {curve && curve.train.length > 1 && (
                  <div>
                    <p className={s.chartLabel}>Learning curve · error by training round</p>
                    <Lines
                      label="Learning curve"
                      height={110}
                      series={[
                        { label: "Train error", values: curve.train, color: "#cfcdd3" },
                        ...(curve.valid
                          ? [
                              {
                                label: `Validation error${row.metrics.best_iteration ? ` (stops improving at round ${row.metrics.best_iteration} → early stop)` : ""}`,
                                values: curve.valid,
                                color: "var(--admin)",
                              },
                            ]
                          : []),
                      ]}
                    />
                  </div>
                )}
              </>
            ) : (
              <p className={s.muted}>{rows.length ? "Select a version." : "This model has not been trained yet. Start training to create a version."}</p>
            )}
          </section>
        </main>

        <aside className={s.col}>
          <section className={s.card}>
            <h2 className={s.h3}>{key.toUpperCase()} versions</h2>
            <div className={s.versions}>
              {rows.map((r) => {
                const newer = activeRow ? r.created_at > activeRow.created_at : true;
                return (
                  <div key={r.version} className={cx(s.version, r.version === version && s.versionOn)}>
                    <button type="button" className={s.versionMain} onClick={() => setVersion(r.version)} aria-pressed={r.version === version}>
                      <strong>{r.version}</strong>
                      <span>
                        {r.active ? "Active" : fmtDay(r.created_at)} · {r.headline.name} {show(r.headline.value, { unit: r.headline.unit })}
                      </span>
                    </button>
                    {r.active ? (
                      <Pill small tone="ok">
                        Active
                      </Pill>
                    ) : (
                      <Button variant={newer ? "admin" : "outline"} loading={busy === `activate:${r.version}`} disabled={Boolean(busy)} onClick={() => void activate(r.version)}>
                        {newer ? "Activate" : "Roll back"}
                      </Button>
                    )}
                  </div>
                );
              })}
              {rows.length === 0 && <p className={s.muted}>No versions yet.</p>}
            </div>
          </section>

          {impact && row && !row.active && (
            <section className={s.impact}>
              <h2>Before you activate {row.version}</h2>
              <p>
                {impact.message} {impact.places_changed} of {impact.places_compared} places change; {impact.trips_affected} saved trips are affected
                and should be re-checked.
              </p>
            </section>
          )}

          {errors && errors.length > 0 && (
            <section className={cx(s.card, s.grow)}>
              <h2 className={s.h3}>Largest errors (test set)</h2>
              <ul className={s.errors}>
                {errors.map((e) => (
                  <li key={`${e.place}-${e.city}`}>
                    <Link href={`/admin/places?q=${encodeURIComponent(e.place)}`}>{e.place}</Link>
                    <span>
                      {e.error_min > 0 ? "+" : ""}
                      {Math.round(e.error_min)} min
                    </span>
                  </li>
                ))}
              </ul>
              <p className={s.pink}>Open a place in D2 to inspect its data.</p>
            </section>
          )}
        </aside>
      </div>
    </Shell>
  );
}
