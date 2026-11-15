"use client";

import { useState, type ReactNode } from "react";
import { TopBar } from "@/components/app/TopBar";
import app from "@/components/app/app.module.css";
import { Button, inputClass } from "@/components/ui";
import { useAccount } from "@/lib/account";
import { useAdmin } from "./admin-store";
import s from "./admin.module.css";

const NAV = [
  { href: "/admin", label: "Data" },
  { href: "/admin/places", label: "Place explorer" },
  { href: "/admin/models", label: "Models" },
  { href: "/admin/optimizer", label: "Optimizer" },
];

/** Data console frame: top bar with the D1–D4 tabs, admin token prompt, error line */
export function Shell({ active, children }: { active: string; children: ReactNode }) {
  const { needsToken, submitToken, error, setError } = useAdmin();
  const account = useAccount();
  const [token, setToken] = useState("");
  return (
    <div className={s.screen}>
      <TopBar
        items={NAV}
        active={active}
        badge={<span className={app.consoleBadge}>Data console</span>}
        right={<span className={s.who}>{account ? `${account.name} · data team` : "Admin · data team"}</span>}
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
          <input className={inputClass} type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Admin token" autoFocus />
          {error && <p className={s.error}>{error}</p>}
          <Button type="submit" variant="admin">
            Sign in
          </Button>
        </form>
      ) : (
        <>
          {error && (
            <p className={s.errorBar} role="alert">
              {error}
              <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
                ×
              </button>
            </p>
          )}
          {children}
        </>
      )}
    </div>
  );
}

export function Stat({ label, value, note, tone }: { label: string; value: ReactNode; note?: ReactNode; tone?: "ok" | "bad" }) {
  return (
    <div className={s.stat}>
      <span className={s.statLabel}>{label}</span>
      <span className={s.statValue} data-tone={tone}>
        {value}
      </span>
      {note && <span className={s.statNote}>{note}</span>}
    </div>
  );
}
