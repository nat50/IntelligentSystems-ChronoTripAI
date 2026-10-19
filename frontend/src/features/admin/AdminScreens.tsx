"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { TopBar } from "@/components/app/TopBar";
import { Button, cx, StatusPill } from "@/components/ui";
import type { ModelState, ModelVersion } from "@/lib/types";
import { useAdmin } from "./admin-store";
import s from "./admin.module.css";

const COUNTRY: Record<string, string> = {
  ID: "Indonesia", MY: "Malaysia", TH: "Thailand", PH: "Philippines", SG: "Singapore", VN: "Vietnam",
  KH: "Cambodia", LA: "Laos", MM: "Myanmar", BN: "Brunei", TL: "Timor-Leste",
};

const MODELS = [
  { key: "m1", name: "M1 · Popularity", desc: "Score per place" },
  { key: "m2", name: "M2 · Hour profile", desc: "Open window, golden hour" },
  { key: "m3", name: "M3 · Visit length", desc: "Minutes per stop" },
] as const;

const fmt = (n: number) => n.toLocaleString("en-US");

function Shell({ active, children }: { active: string; children: ReactNode }) {
  const { needsToken, submitToken, error } = useAdmin();
  const [token, setToken] = useState("");
  return (
    <div className={s.screen}>
      <TopBar
        items={[
          { href: "/admin", label: "Data" },
          { href: "/admin/models", label: "Models" },
        ]}
        active={active}
        right={<span>Admin</span>}
      />
      {needsToken ? (
        <form
          className={s.tokenForm}
          onSubmit={(e) => {
            e.preventDefault();
            submitToken(token);
          }}
        >
          <h1 className={s.h2}>Admin sign in</h1>
          <p className={s.sub}>Enter the admin token configured on the server (CHRONOTRIP_ADMIN_TOKEN).</p>
          <input className={s.input} type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Admin token" autoFocus />
          {error && <p className={s.error} role="alert">{error}</p>}
          <Button type="submit">Sign in</Button>
        </form>
      ) : (
        children
      )}
    </div>
  );
}

function SidePanel() {
  const { overview, dataset, busy, train, activate, download, error } = useAdmin();
  const job = overview?.job;
  const jobLive = job && (job.status === "running" || job.status === "queued");
  const hasActive = overview?.versions.some((v) => v.is_active);
  const states: Record<string, ModelState> = jobLive ? job.models : {};
  const stateOf = (k: string): ModelState => states[k] ?? (hasActive ? "trained" : "queued");
  const p = dataset?.progress;
  const pct = p?.total ? Math.round((100 * (p.done ?? 0)) / p.total) : 0;

  return (
    <div className={s.side}>
      {MODELS.map((m) => (
        <div key={m.key} className={s.model}>
          <div>
            <p className={s.modelName}>{m.name}</p>
            <p className={s.modelDesc}>{m.desc}</p>
          </div>
          <StatusPill state={stateOf(m.key)} />
        </div>
      ))}

      <div className={s.block}>
        <p className={s.blockTitle}>Versions</p>
        {overview?.versions.length === 0 && <p className={s.message}>No model version yet.</p>}
        {overview?.versions.slice(0, 5).map((v) => (
          <div key={v.version} className={s.version}>
            <div>
              <p className={s.versionName}>{v.version}</p>
              <p className={s.versionMeta}>
                {v.source === "dataset" ? "LBSN2Vec++" : "synthetic sample"} · {fmt(v.places)} places ·{" "}
                {new Date(v.created_at).toLocaleDateString()}
              </p>
            </div>
            {v.is_active ? (
              <span className={s.activeLabel}>Active</span>
            ) : (
              <Button variant="outline" onClick={() => activate(v.version)} loading={busy === `activate:${v.version}`}>
                Activate
              </Button>
            )}
          </div>
        ))}
      </div>

      <div className={s.spacer} />

      {dataset && !dataset.found && (
        <div className={s.block}>
          <p className={s.blockTitle}>LBSN2Vec++ dataset</p>
          {dataset.running ? (
            <>
              <div className={s.progress} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <div className={s.progressFill} style={{ width: `${pct}%` }} />
              </div>
              <p className={s.message}>
                {p?.stage === "verifying" ? "Verifying checksum" : "Downloading"} · {((p?.done ?? 0) / 1e9).toFixed(2)} /{" "}
                {((p?.total ?? 0) / 1e9).toFixed(2)} GB
                {p?.speed ? ` · ${(p.speed / 1e6).toFixed(1)} MB/s` : ""}
              </p>
            </>
          ) : (
            <>
              <p className={s.message}>
                Not downloaded yet. Training will fall back to a synthetic sample until it is. 2.68 GB from 4TU.ResearchData (CC BY 4.0).
              </p>
              <Button variant="outline" onClick={download} loading={busy === "download"}>
                Download dataset (2.68 GB)
              </Button>
            </>
          )}
          {dataset.error && <p className={s.error}>{dataset.error}</p>}
        </div>
      )}

      {job && (
        <p className={s.message} aria-live="polite">
          Job #{job.id} · {job.status} · {job.message}
        </p>
      )}
      {error && <p className={s.error}>{error}</p>}
      <Button block onClick={train} loading={busy === "train" || Boolean(jobLive)} disabled={Boolean(jobLive) || dataset?.running}>
        {jobLive ? "Training…" : "Train models"}
      </Button>
    </div>
  );
}

export function DataScreen() {
  const { overview } = useAdmin();
  const stats = (overview?.country_stats ?? []).slice(0, 6); // Figma + spec Table 2: the six largest
  const max = Math.max(1, ...stats.map((x) => x.checkins));
  const measured = stats[0]?.source !== "dataset";
  return (
    <Shell active="/admin">
      <div className={s.body}>
        <section className={cx(s.card, s.main)}>
          <h1 className={s.h2}>Check-ins by country</h1>
          <p className={s.sub}>
            LBSN2Vec++ · Southeast Asia · Apr 2012 – Jan 2014
            <span className={s.source}>{measured ? "measured on raw files" : "from your preprocessing run"}</span>
          </p>
          <div className={s.bars}>
            {stats.map((x, i) => {
              const vn = x.country === "VN";
              return (
                <div key={x.country} className={s.barRow}>
                  <span className={cx(s.country, vn && s.countryVn)}>{COUNTRY[x.country] ?? x.country}</span>
                  <span className={s.track}>
                    <span
                      className={cx(s.bar, vn && s.barVn)}
                      style={{ width: `${(70 * x.checkins) / max}%`, "--delay": `${i * 90}ms` } as CSSProperties}
                    />
                    <span className={s.value}>{fmt(x.checkins)}</span>
                  </span>
                </div>
              );
            })}
          </div>
          <p className={s.note}>
            Vietnam has only 48,357 check-ins — about 160× fewer than Indonesia — so the models are trained on all of
            Southeast Asia and then applied to Ho Chi Minh City and Hanoi. Every predicted attribute carries a
            confidence level from its number of check-ins: high (≥ 30), medium (10–29) or low (&lt; 10, category
            estimate, opening hours treated as a soft constraint).
          </p>
        </section>
        <SidePanel />
      </div>
    </Shell>
  );
}

function compare(model: number | null | undefined, base: number | null | undefined, higherIsBetter: boolean) {
  if (model == null || base == null) return <td>—</td>;
  const better = higherIsBetter ? model >= base : model <= base;
  return (
    <td>
      <span className={better ? s.better : s.worse}>{model.toFixed(3)}</span>
      <span className={s.versionMeta}> vs {base.toFixed(3)}</span>
    </td>
  );
}

function MetricsTable({ versions }: { versions: ModelVersion[] }) {
  return (
    <table className={s.table}>
      <thead>
        <tr>
          <th>Version</th>
          <th>M1 Spearman ↑ (vs raw count)</th>
          <th>M2 log-lik ↑ (vs category)</th>
          <th>M3 pinball ↓ (vs category median)</th>
        </tr>
      </thead>
      <tbody>
        {versions.map((v) => (
          <tr key={v.version}>
            <td>
              <strong>{v.version}</strong>
              {v.is_active && <span className={s.activeLabel}> · active</span>}
              <div className={s.versionMeta}>{v.source === "dataset" ? "LBSN2Vec++" : "synthetic sample"}</div>
            </td>
            {compare(v.metrics.m1?.spearman_all ?? v.metrics.m1?.spearman, v.metrics.m1?.spearman_all_baseline ?? v.metrics.m1?.spearman_baseline, true)}
            {compare(v.metrics.m2?.loglik, v.metrics.m2?.loglik_baseline, true)}
            {compare(v.metrics.m3?.pinball, v.metrics.m3?.pinball_baseline, false)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ModelsScreen() {
  const { overview } = useAdmin();
  return (
    <Shell active="/admin/models">
      <div className={s.body}>
        <section className={cx(s.card, s.main)}>
          <h1 className={s.h2}>Model evaluation</h1>
          <p className={s.sub}>Test period Nov 2013 – Jan 2014 · each model against its baseline (green = better)</p>
          {overview && overview.versions.length > 0 ? (
            <MetricsTable versions={overview.versions} />
          ) : (
            <p className={s.message}>Train a version to see its metrics.</p>
          )}
          <p className={s.note}>
            M1 — LightGBM on category, city, location and nearby density; label log(1 + distinct users). M2 —
            hierarchical Dirichlet–Multinomial (category and city as priors), circular 24 h smoothing; opening window =
            90% of check-ins, golden hour = densest 120 min. M3 — quantile gradient boosting on the gap between
            consecutive check-ins minus estimated travel. Effort e<sub>i</sub> is a lookup by category.
          </p>
        </section>
        <SidePanel />
      </div>
    </Shell>
  );
}
