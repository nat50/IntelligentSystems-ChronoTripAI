"use client";

import Link from "next/link";
import { Fragment, useCallback, useState } from "react";
import { Button, Pill, type Tone } from "@/components/ui";
import { api } from "@/lib/api";
import type { DataOverview, DatasetStatus } from "@/lib/types";
import { fmt, fmtDay, fmtShort, fmtStamp, pollJob, useAdmin, useAdminData } from "./admin-store";
import { Shell, Stat } from "./Shell";
import s from "./admin.module.css";

const SOURCE_TONE: Record<DataOverview["sources"][number]["status"], Tone> = {
  imported: "ok",
  synced: "ok",
  online: "ok",
  outdated: "warn",
  estimate: "warn",
  missing: "bad",
};
const IMPACT_TONE = { high: "bad", medium: "warn", low: "neutral" } as const;
const ACTION_LABEL = { crawl_hours: "Re-crawl", retrain: "Retrain", review_places: "Review" } as const;

const cap = (t: string) => t[0].toUpperCase() + t.slice(1);

/** Figma D1 · Data (84:205) */
export function DataScreen() {
  const { call } = useAdmin();
  const [data, reload] = useAdminData(useCallback(() => api.data(), []));
  const [dataset, reloadDataset] = useAdminData(useCallback(() => api.dataset(), []));
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const runPipeline = async () => {
    setBusy("train");
    const job = await call(() => api.train("auto"));
    if (job) {
      setStatus(`Pipeline running · ${job.message}`);
      const done = await call(() => pollJob(job, (j) => setStatus(`Pipeline running · ${j.message}`)));
      setStatus(done ? `Pipeline ${done.status} · ${done.message}` : null);
      await reload();
    }
    setBusy(null);
  };

  const crawl = async () => {
    setBusy("crawl");
    let st = await call(() => api.crawlHours());
    while (st?.running) {
      setStatus("Crawling opening hours from OpenStreetMap…");
      await new Promise((r) => setTimeout(r, 2000));
      st = await call(() => api.hours());
    }
    if (st) setStatus(st.error ? `Crawl failed · ${st.error}` : `Crawl done · ${fmt(st.usable)} places with usable hours. Run the pipeline to apply them.`);
    await reload();
    setBusy(null);
  };

  const download = async () => {
    setBusy("download");
    let st: DatasetStatus | undefined = await call(() => api.downloadDataset());
    while (st?.running) {
      const p = st.progress;
      setStatus(`Downloading LBSN2Vec++ · ${((p?.done ?? 0) / 1e9).toFixed(2)} / ${((p?.total ?? 0) / 1e9).toFixed(2)} GB`);
      await new Promise((r) => setTimeout(r, 2000));
      st = await call(() => api.dataset());
    }
    setStatus(st?.error ? `Download failed · ${st.error}` : null);
    await reloadDataset();
    setBusy(null);
  };

  const ready = data?.cities.filter((c) => c.ready) ?? [];

  return (
    <Shell active="/admin">
      <main className={s.main}>
        <div className={s.head}>
          <div>
            <h1 className={s.h1}>Data</h1>
            <p className={s.sub}>Sources used by the three estimate models · dataset {data?.dataset_version ?? "—"}</p>
          </div>
          <div className={s.headActions}>
            {dataset && !dataset.found && (
              <Button variant="outline" onClick={download} loading={busy === "download"} disabled={Boolean(busy)}>
                Download dataset (2.68 GB)
              </Button>
            )}
            <Button variant="admin" onClick={runPipeline} loading={busy === "train"} disabled={Boolean(busy)}>
              Run pipeline
            </Button>
          </div>
        </div>
        {status && (
          <p className={s.status} aria-live="polite">
            {status}
          </p>
        )}

        <div className={s.stats4}>
          <Stat label="Check-ins" value={fmtShort(data?.checkins)} note={data?.checkins_period} />
          <Stat label="Places (POIs)" value={fmt(data?.places)} note="POI = point of interest" />
          <Stat label="Cities ready" value={data ? `${ready.length} of ${data.cities.length}` : "—"} note={ready.map((c) => c.name).join(", ") || "None yet"} />
          <Stat
            label="Last pipeline run"
            value={fmtStamp(data?.last_run)}
            note={data?.last_run_minutes != null ? `Completed in ${Math.round(data.last_run_minutes)} min` : "Not run yet"}
          />
        </div>

        <div className={s.split}>
          <div className={s.col}>
            <section className={s.card}>
              <h2 className={s.h3}>Sources ({data?.sources.length ?? 0})</h2>
              <div className={s.tableWrap}>
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Provides</th>
                      <th>Rows</th>
                      <th>Updated</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data?.sources.map((x) => (
                      <tr key={x.key}>
                        <td className={s.strong}>{x.name}</td>
                        <td>{x.provides}</td>
                        <td>{fmtShort(x.rows)}</td>
                        <td>{x.updated ? fmtDay(x.updated) : x.key === "checkins" ? "Static 2014" : "—"}</td>
                        <td>
                          <Pill small tone={SOURCE_TONE[x.status]}>
                            {cap(x.status)}
                          </Pill>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className={s.card}>
              <h2 className={s.h3}>Pipeline · last run</h2>
              <ol className={s.pipeline}>
                {data?.pipeline.map((p, i) => (
                  <Fragment key={p.key}>
                    {i > 0 && (
                      <li className={s.arrow} aria-hidden>
                        →
                      </li>
                    )}
                    <li className={s.step} data-last={i === data.pipeline.length - 1 || undefined}>
                      <strong>
                        {i + 1} {p.label}
                      </strong>
                      <span>{p.value}</span>
                    </li>
                  </Fragment>
                ))}
              </ol>
              <p className={s.note}>
                Opening hours are matched to the nearest place of the same category within 100 m. Unmatched places keep
                hours estimated from check-ins.
              </p>
            </section>
          </div>

          <section className={s.card}>
            <div className={s.cardHead}>
              <h2 className={s.h3}>Quality issues ({data?.issues.length ?? 0})</h2>
              <span className={s.muted}>Sorted by impact</span>
            </div>
            {data?.issues.length === 0 && <p className={s.muted}>No open issues.</p>}
            <div className={s.issues}>
              {data?.issues.map((x) => (
                <div key={x.key} className={s.issue}>
                  <div className={s.issueTitle}>
                    <Pill small tone={IMPACT_TONE[x.impact]}>
                      {cap(x.impact)}
                    </Pill>
                    <strong>{x.title}</strong>
                  </div>
                  <div className={s.issueFoot}>
                    <span>{x.detail}</span>
                    {x.action === "review_places" && (
                      <Link className={s.action} href="/admin/places?quality=low_data">
                        {ACTION_LABEL[x.action]}
                      </Link>
                    )}
                    {x.action === "crawl_hours" && (
                      <button type="button" className={s.action} onClick={crawl} disabled={Boolean(busy)}>
                        {ACTION_LABEL[x.action]}
                      </button>
                    )}
                    {x.action === "retrain" && (
                      <button type="button" className={s.action} onClick={runPipeline} disabled={Boolean(busy)}>
                        {ACTION_LABEL[x.action]}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </Shell>
  );
}
