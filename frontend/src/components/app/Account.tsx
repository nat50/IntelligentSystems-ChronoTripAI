"use client";

import { useState } from "react";
import { Button, Field, inputClass, Modal } from "@/components/ui";
import { signIn, signOut, useAccount } from "@/lib/account";
import s from "./app.module.css";

/** Top-bar "Sign in" / "My account". Mock only: see lib/account.ts */
export function AccountMenu() {
  const account = useAccount();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");

  if (account) {
    return (
      <span className={s.account}>
        <button type="button" className={s.topLink} aria-expanded={menu} onClick={() => setMenu((m) => !m)}>
          My account
        </button>
        {menu && (
          <span className={s.accountMenu} role="menu">
            <span className={s.accountName}>{account.name}</span>
            <span className={s.accountEmail}>{account.email}</span>
            <button
              type="button"
              role="menuitem"
              className={s.accountItem}
              onClick={() => {
                signOut();
                setMenu(false);
              }}
            >
              Sign out
            </button>
          </span>
        )}
      </span>
    );
  }

  return (
    <>
      <button type="button" className={s.topLink} onClick={() => setOpen(true)}>
        Sign in
      </button>
      {open && (
        <Modal title="Sign in" onClose={() => setOpen(false)}>
          <form
            className={s.signIn}
            onSubmit={(e) => {
              e.preventDefault();
              signIn({ name: name.trim() || email.split("@")[0], email: email.trim() });
              setOpen(false);
            }}
          >
            <p className={s.signInNote}>Demo sign-in: your name stays in this browser only. Saved trips work without an account.</p>
            <Field label="Name">
              <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </Field>
            <Field label="Email">
              <input className={inputClass} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            </Field>
            <div className={s.signInActions}>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit">Sign in</Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
