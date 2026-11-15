"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, ApiError, setAdminToken } from "@/lib/api";
import type { Job } from "@/lib/types";

interface AdminCtx {
  needsToken: boolean;
  error: string | null;
  setError: (e: string | null) => void;
  submitToken: (t: string) => void;
  /** runs an admin request; a 401 asks for the token, other errors show in the console */
  call: <T>(fn: () => Promise<T>) => Promise<T | undefined>;
  version: number; // bumps after a new token so screens refetch
}

const Ctx = createContext<AdminCtx | null>(null);

export function AdminProvider({ children }: { children: React.ReactNode }) {
  const [needsToken, setNeedsToken] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  const call = useCallback(async <T,>(fn: () => Promise<T>) => {
    try {
      const out = await fn();
      setNeedsToken(false);
      return out;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setNeedsToken(true);
        setError("The admin token is missing or invalid.");
      } else setError(e instanceof Error ? e.message : String(e));
      return undefined;
    }
  }, []);

  const value = useMemo<AdminCtx>(
    () => ({
      needsToken,
      error,
      setError,
      call,
      version,
      submitToken: (t) => {
        setAdminToken(t);
        setError(null);
        setNeedsToken(false);
        setVersion((v) => v + 1);
      },
    }),
    [needsToken, error, call, version],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAdmin() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAdmin must be used inside <AdminProvider>");
  return c;
}

/** Loads admin data on mount and after a new token. `fetcher` must be stable (useCallback). */
export function useAdminData<T>(fetcher: () => Promise<T>) {
  const { call, version } = useAdmin();
  const [data, setData] = useState<T | null>(null);
  const reload = useCallback(async () => {
    const d = await call(fetcher);
    if (d !== undefined) setData(d);
  }, [call, fetcher]);
  useEffect(() => {
    const id = setTimeout(() => void reload(), 0);
    return () => clearTimeout(id);
  }, [reload, version]);
  return [data, reload] as const;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Waits for a training / activation job to finish */
export async function pollJob(job: Job, onTick?: (j: Job) => void): Promise<Job> {
  let j = job;
  while (j.status === "queued" || j.status === "running") {
    await sleep(1500);
    j = await api.job(j.id);
    onTick?.(j);
  }
  return j;
}

export const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toLocaleString("en-US"));

/** 18_240_000 -> "18.24 M" */
export const fmtShort = (n: number | null | undefined) =>
  n == null ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(2)} M` : n >= 1e4 ? `${(n / 1e3).toFixed(1)} K` : fmt(n);

export const fmtDay = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";

/** "06 Nov · 02:10" */
export const fmtStamp = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })} · ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
};
