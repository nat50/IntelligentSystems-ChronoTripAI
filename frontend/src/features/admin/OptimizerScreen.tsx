"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Field, inputClass, Pill, Slider, Toggle } from "@/components/ui";
import { Lines } from "@/components/ui/charts";
import { api } from "@/lib/api";
import type { Benchmark, OptimizerSettings } from "@/lib/types";
import { useAdmin, useAdminData } from "./admin-store";
import { rebalance, type Weight } from "./rebalance";
import { Shell, Stat } from "./Shell";
import s from "./admin.module.css";

const WEIGHTS: { key: Weight; label: string }[] = [
  { key: "popularity", label: "Popularity of places (M1)" },
  { key: "golden", label: "Visiting in golden hour (M2)" },
  { key: "travel", label: "Penalty for travel time" },
];

const same = (a: OptimizerSettings, b: OptimizerSettings) => JSON.stringify(a) === JSON.stringify(b);

/** Figma D4 · Optimizer (85:395) */
export function OptimizerScreen() {
  const { call } = useAdmin();
  const [info, reload] = useAdminData(useCallback(() => api.optimizer(), []));
  const [form, setForm] = useState<OptimizerSettings | null>(null);
  const [bench, setBench] = useState<Benchmark | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  const settings = form ?? info?.active ?? null;
  const shown = bench ?? info?.last_benchmark ?? null;

  // keep polling a benchmark that is still running (e.g. started before a reload)
  useEffect(() => {
    if (shown?.status !== "running") return;
    const id = setInterval(() => void call(() => api.pollBenchmark(shown.id)).then((b) => b && setBench(b)), 2000);
    return () => clearInterval(id);
  }, [shown?.status, shown?.id, call]);

  if (!settings) return <Shell active="/admin/optimizer">{null}</Shell>;

  const set = (patch: Partial<OptimizerSettings>) => {
    setApplied(false);
    setForm({ ...settings, ...patch });
  };
  const num = (k: "population" | "generations" | "crossover" | "mutation" | "time_limit_s") => (e: React.ChangeEvent<HTMLInputElement>) =>
    set({ [k]: Number(e.target.value) });

  const run = async () => {
    setBusy("bench");
    const b = await call(() => api.benchmark(settings));
    if (b) setBench(b);
    setBusy(null);
  };

  const apply = async () => {
    setBusy("apply");
    const out = await call(() => api.applyOptimizer(settings));
    if (out) {
      setForm(null);
      setApplied(true);
      await reload();
    }
    setBusy(null);
  };

  const testedNow = shown?.status === "done" && same(shown.settings, settings);
  const isActive = info ? same(info.active, settings) : false;
  const change = shown?.score_change;

  return (
    <Shell active="/admin/optimizer">
      <div className={s.optimizer}>
        <aside className={s.formPanel}>
          <div>
            <h1 className={s.h1}>Optimizer</h1>
            <p className={s.sub}>
              Memetic genetic algorithm for TOPTW (Team Orienteering Problem with Time Windows): choose and order stops for
              several days so that total value is highest and every stop is inside its opening hours.
            </p>
          </div>
          <div className={s.grid2}>
            <Field label="Population size">
              <input className={inputClass} type="number" min={10} max={400} value={settings.population} onChange={num("population")} />
            </Field>
            <Field label="Generations">
              <input className={inputClass} type="number" min={10} max={2000} value={settings.generations} onChange={num("generations")} />
            </Field>
            <Field label="Crossover rate">
              <input className={inputClass} type="number" min={0} max={1} step={0.05} value={settings.crossover} onChange={num("crossover")} />
            </Field>
            <Field label="Mutation rate">
              <input className={inputClass} type="number" min={0} max={1} step={0.05} value={settings.mutation} onChange={num("mutation")} />
            </Field>
            <Field label="Time limit per request (s)">
              <input className={inputClass} type="number" min={0.5} max={30} step={0.5} value={settings.time_limit_s} onChange={num("time_limit_s")} />
            </Field>
            <div className={s.field}>
              <span>Local search (2-opt)</span>
              <span className={s.toggleRow}>
                <Toggle label="Local search" checked={settings.local_search} onChange={(on) => set({ local_search: on })} />
                {settings.local_search ? "On" : "Off"}
              </span>
            </div>
          </div>
          <div className={s.weights}>
            <span className={s.muted}>Objective weights (sum = 1.0)</span>
            {WEIGHTS.map((w) => (
              <div key={w.key} className={s.weight}>
                <span>{w.label}</span>
                <strong>{settings.objective[w.key].toFixed(2)}</strong>
                <Slider label={w.label} min={0} max={1} step={0.05} value={settings.objective[w.key]} onChange={(v) => set({ objective: rebalance(settings.objective, w.key, v) })} />
              </div>
            ))}
          </div>
          <div className={s.grid2}>
            <Button variant="outline" onClick={run} loading={busy === "bench" || shown?.status === "running"} disabled={Boolean(busy) || shown?.status === "running"}>
              Run benchmark
            </Button>
            <Button variant="admin" onClick={apply} loading={busy === "apply"} disabled={Boolean(busy) || isActive || !testedNow || !shown?.ready_to_apply}>
              Apply to planner
            </Button>
          </div>
          <p className={s.note}>
            {applied
              ? "Applied. Every new itinerary now uses these settings."
              : isActive
                ? "These are the settings the planner uses now."
                : testedNow
                  ? shown?.ready_to_apply
                    ? "Benchmarked: ready to apply."
                    : "Not ready: the score dropped, a rule was broken or it ran too long."
                  : "Run a benchmark of these settings before applying them."}
          </p>
        </aside>

        <main className={s.benchMain}>
          <div className={s.head}>
            <div>
              <h2 className={s.h1}>Benchmark · new settings vs active</h2>
              <p className={s.sub}>
                {shown ? `${shown.cases.length || 4} fixed test cases · each run 3 times · median shown` : "No benchmark yet. Change a setting and run one."}
              </p>
            </div>
            {shown?.status === "done" && (
              <Pill small tone={shown.ready_to_apply ? "ok" : "warn"}>
                {shown.ready_to_apply ? "Ready to apply" : "Not ready"}
              </Pill>
            )}
            {shown?.status === "running" && <Pill small tone="admin">Running · about 1–2 min</Pill>}
            {shown?.status === "failed" && <Pill small tone="bad">Failed</Pill>}
          </div>
          {shown?.error && <p className={s.error}>{shown.error}</p>}
          {shown && shown.status !== "running" && (
            <>
              <div className={s.grid3}>
                <Stat
                  label="Score change"
                  value={change == null ? "—" : `${change >= 0 ? "+" : ""}${(change * 100).toFixed(1)}%`}
                  tone={change == null ? undefined : change >= 0 ? "ok" : "bad"}
                  note="vs active settings"
                />
                <Stat label="Rule violations" value={shown.violations ?? "—"} tone={shown.violations ? "bad" : undefined} note="opening hours and day limits" />
                <Stat
                  label="Median run time"
                  value={shown.median_runtime_s == null ? "—" : `${shown.median_runtime_s.toFixed(1)} s`}
                  note={`limit ${shown.settings.time_limit_s} s`}
                />
              </div>
              {shown.curve && shown.curve.generation.length > 1 && (
                <section className={s.card}>
                  <h3 className={s.h3}>
                    Best score by generation{shown.cases[0] ? ` (${shown.cases[0].name})` : ""}
                  </h3>
                  <Lines
                    label="Best score by generation"
                    height={140}
                    ticks={[0, 0.5, 1].map((f) => String(Math.round(f * shown.curve!.generation[shown.curve!.generation.length - 1])))}
                    series={[
                      { label: "Active settings", values: shown.curve.active, color: "#cfcdd3", dashed: true },
                      { label: "New settings", values: shown.curve.new, color: "var(--accent)" },
                    ]}
                  />
                </section>
              )}
              <section className={s.card}>
                <div className={s.tableWrap}>
                  <table className={s.table}>
                    <thead>
                      <tr>
                        <th>Test case</th>
                        <th>Score (active)</th>
                        <th>Score (new)</th>
                        <th>Violations</th>
                        <th>Run time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.cases.map((c) => (
                        <tr key={c.name}>
                          <td className={s.strong}>{c.name}</td>
                          <td>{c.score_active.toFixed(2)}</td>
                          <td>{c.score_new.toFixed(2)}</td>
                          <td>{c.violations}</td>
                          <td>{c.runtime_s.toFixed(1)} s</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </Shell>
  );
}
