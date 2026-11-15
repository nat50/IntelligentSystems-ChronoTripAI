"use client";

import { useSyncExternalStore } from "react";

// shortcut: mock sign-in kept in localStorage only; the backend has no accounts yet.
// Replace with a real auth provider when the API gets one.
const KEY = "chronotrip.account.v1";
const EVENT = "chronotrip-account";

export interface Account {
  name: string;
  email: string;
}

let cachedRaw: string | null | undefined;
let cached: Account | null = null;

function read(): Account | null {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    /* storage blocked */
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      const v = raw ? JSON.parse(raw) : null;
      cached = v && typeof v.name === "string" && typeof v.email === "string" ? v : null;
    } catch {
      cached = null;
    }
  }
  return cached;
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useAccount(): Account | null {
  return useSyncExternalStore(subscribe, read, () => null);
}

export function signIn(account: Account) {
  try {
    localStorage.setItem(KEY, JSON.stringify(account));
  } catch {
    /* storage blocked: the demo sign-in cannot be kept */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function signOut() {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event(EVENT));
}
