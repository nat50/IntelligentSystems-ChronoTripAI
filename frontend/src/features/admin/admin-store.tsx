"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError, setAdminToken } from "@/lib/api";
import type { AdminOverview, DatasetStatus } from "@/lib/types";

interface AdminCtx {
  overview: AdminOverview | null;
  dataset: DatasetStatus | null;
  needsToken: boolean;
  error: string | null;
  busy: string | null;
  refresh: () => Promise<void>;
  submitToken: (t: string) => void;
  train: () => Promise<void>;
  activate: (v: string) => Promise<void>;
  download: () => Promise<void>;
}

const Ctx = createContext<AdminCtx | null>(null);

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [dataset, setDataset] = useState<DatasetStatus | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const handle = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) {
      setNeedsToken(true);
      setError("The admin token is invalid. Please try again.");
    } else setError(e instanceof Error ? e.message : String(e));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [o, d] = await Promise.all([api.overview(), api.dataset()]);
      setOverview(o);
      setDataset(d);
      setNeedsToken(false);
      setError(null);
    } catch (e) {
      handle(e);
    }
  }, [handle]);

  useEffect(() => {
    const id = setTimeout(() => void refresh(), 0);
    return () => clearTimeout(id);
  }, [refresh]);

  // poll while something runs in the background
  const running = overview?.job?.status === "running" || overview?.job?.status === "queued" || dataset?.running;
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => void refresh(), 2000);
    return () => clearInterval(id);
  }, [running, refresh]);

  const act = useCallback(
    async (name: string, fn: () => Promise<unknown>) => {
      setBusy(name);
      setError(null);
      try {
        await fn();
        await refresh();
      } catch (e) {
        handle(e);
      } finally {
        setBusy(null);
      }
    },
    [refresh, handle],
  );

  const value = useMemo<AdminCtx>(
    () => ({
      overview,
      dataset,
      needsToken,
      error,
      busy,
      refresh,
      submitToken: (t) => {
        setAdminToken(t);
        void refresh();
      },
      train: () => act("train", () => api.train("auto")),
      activate: (v) => act(`activate:${v}`, () => api.activate(v)),
      download: () => act("download", () => api.downloadDataset()),
    }),
    [overview, dataset, needsToken, error, busy, refresh, act],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAdmin() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAdmin must be used inside <AdminProvider>");
  return c;
}
