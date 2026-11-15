"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AccountMenu } from "@/components/app/Account";
import { TopBar } from "@/components/app/TopBar";
import { Button, cx, Field, inputClass, Modal, Slider } from "@/components/ui";
import { clock, duration } from "@/lib/time";
import { INTERESTS, useTrip } from "@/lib/trip-store";
import type { Point } from "@/lib/types";
import { planNav } from "../plan-nav";
import scr from "../screen.module.css";
import s from "./setup.module.css";

const MapView = dynamic(() => import("@/components/map/MapView"), { ssr: false });

const SLOTS = Array.from({ length: 39 }, (_, i) => 5 * 60 + i * 30); // 05:00 … 24:00

const PACES = [
  { value: 0, label: "Relaxed", hint: "Relaxed ≈ 3–4 stops per day with long breaks." },
  { value: 0.5, label: "Balanced", hint: "Balanced ≈ 5–6 stops per day with short breaks." },
  { value: 1, label: "Packed", hint: "Packed ≈ 7+ stops per day, little waiting." },
];

const STEPS = [
  ["Set your trip", "Dates, daily hours and where you stay."],
  ["Pick places", "See the best time and typical visit length of each place."],
  ["Get a plan you can edit", "Reorder, lock or remove stops, then re-optimize."],
];

export function TripSetupScreen() {
  const router = useRouter();
  const { state, dispatch, cities } = useTrip();
  const [more, setMore] = useState(false);
  const [stayOpen, setStayOpen] = useState(false);
  const pace = PACES.reduce((a, b) => (Math.abs(b.value - state.prefs.pace) < Math.abs(a.value - state.prefs.pace) ? b : a));
  const city = cities.find((c) => c.name === state.city);

  return (
    <div className={scr.page}>
      <TopBar
        items={planNav(state, "/plan")}
        active="/plan"
        right={
          <>
            <Link href="/plan/trips" className={scr.topLink}>
              Saved trips
            </Link>
            <AccountMenu />
          </>
        }
      />
      <main className={s.main}>
        <section className={s.intro}>
          <p className={s.eyebrow}>Itinerary planner</p>
          <h1 className={s.h1}>Plan your trip around real opening hours.</h1>
          <p className={s.lead}>
            ChronoTrip orders your stops using opening hours, travel time and the busiest hours learned from 18M real
            check-ins.
          </p>
          <ol className={s.steps}>
            {STEPS.map(([title, text], i) => (
              <li key={title}>
                <span className={s.stepNo}>{i + 1}</span>
                <span>
                  <strong>{title}</strong>
                  <span>{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>

        <form
          className={s.card}
          onSubmit={(e) => {
            e.preventDefault();
            router.push("/plan/places");
          }}
        >
          <div>
            <h2 className={s.h2}>Trip setup</h2>
            <p className={s.sub}>Step 1 of 3 · you can change every field later.</p>
          </div>

          <Field label="Destination" hint={cities.length > 0 && `Available now: ${cities.map((c) => c.name).join(", ")}`}>
            <span className={s.withAction}>
              <select className={inputClass} value={state.city} onChange={(e) => dispatch({ type: "city", city: e.target.value })}>
                {(cities.length ? cities.map((c) => c.name) : [state.city]).map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
              <span className={s.action} aria-hidden>
                Change
              </span>
            </span>
          </Field>

          <div className={s.grid2}>
            <Field label="Start date">
              <input
                className={inputClass}
                type="date"
                value={state.startDate ?? ""}
                onChange={(e) => dispatch({ type: "startDate", date: e.target.value || null })}
              />
            </Field>
            <Field label="Days">
              <span className={s.stepper}>
                <button type="button" aria-label="One day less" disabled={state.days <= 1} onClick={() => dispatch({ type: "days", days: state.days - 1 })}>
                  −
                </button>
                <span aria-live="polite">
                  {state.days} {state.days === 1 ? "day" : "days"}
                </span>
                <button type="button" aria-label="One more day" disabled={state.days >= 3} onClick={() => dispatch({ type: "days", days: state.days + 1 })}>
                  +
                </button>
              </span>
            </Field>
            <Field label="Day starts">
              <select
                className={inputClass}
                value={state.dayStart}
                onChange={(e) => {
                  const start = Number(e.target.value);
                  dispatch({ type: "hours", dayStart: start, dayEnd: Math.max(state.dayEnd, start + 120) });
                }}
              >
                {SLOTS.filter((m) => m <= 20 * 60).map((m) => (
                  <option key={m} value={m}>
                    {clock(m)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Day ends" hint={`${duration(state.dayEnd - state.dayStart)} available per day`}>
              <select
                className={inputClass}
                value={state.dayEnd}
                onChange={(e) => dispatch({ type: "hours", dayStart: state.dayStart, dayEnd: Number(e.target.value) })}
              >
                {SLOTS.filter((m) => m >= state.dayStart + 120).map((m) => (
                  <option key={m} value={m}>
                    {m === 1440 ? "24:00" : clock(m)}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Stay (start and end point)">
            <button type="button" className={cx(inputClass, s.fakeInput)} onClick={() => setStayOpen(true)}>
              <span>{state.stay?.label ?? "Choose where you stay"}</span>
              <span className={s.action}>Change</span>
            </button>
          </Field>

          <div className={s.block}>
            <span className={s.label} id="pace-label">
              Pace
            </span>
            <div className={s.segment} role="radiogroup" aria-labelledby="pace-label">
              {PACES.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  role="radio"
                  aria-checked={p === pace}
                  className={cx(p === pace && s.segmentOn)}
                  onClick={() => dispatch({ type: "prefs", prefs: { pace: p.value } })}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <span className={s.hint}>{pace.hint}</span>
          </div>

          <button type="button" className={s.more} aria-expanded={more} onClick={() => setMore((m) => !m)}>
            {more ? "Fewer options" : "More options"}
          </button>
          {more && (
            <div className={s.moreBox}>
              <div className={s.block}>
                <span className={s.label}>Travel</span>
                <Slider label="Travel" value={state.prefs.travel} onChange={(v) => dispatch({ type: "prefs", prefs: { travel: v } })} />
                <span className={s.scale}>
                  <span>Go anywhere</span>
                  <span>Keep it close</span>
                </span>
              </div>
              <div className={s.block}>
                <span className={s.label}>Opening hours and meals</span>
                <Slider
                  label="Opening hours and meals"
                  value={state.prefs.strictness}
                  onChange={(v) => dispatch({ type: "prefs", prefs: { strictness: v } })}
                />
                <span className={s.scale}>
                  <span>Flexible</span>
                  <span>Strict</span>
                </span>
              </div>
            </div>
          )}

          <div className={s.block}>
            <span className={s.label}>Interests (optional)</span>
            <div className={s.chips}>
              {INTERESTS.map((i) => {
                const on = state.interests.includes(i.key);
                return (
                  <button
                    key={i.key}
                    type="button"
                    aria-pressed={on}
                    className={cx(scr.chip, on && scr.chipOn)}
                    onClick={() =>
                      dispatch({ type: "interests", interests: on ? state.interests.filter((k) => k !== i.key) : [...state.interests, i.key] })
                    }
                  >
                    {i.label}
                  </button>
                );
              })}
            </div>
          </div>

          <Button type="submit" block disabled={!state.stay}>
            Continue to places
          </Button>
        </form>
      </main>

      {stayOpen && city && (
        <StayDialog
          stay={state.stay ?? { ...city.stay }}
          onClose={() => setStayOpen(false)}
          onSave={(stay) => {
            dispatch({ type: "stay", stay });
            setStayOpen(false);
          }}
        />
      )}
    </div>
  );
}

function StayDialog({
  stay,
  onClose,
  onSave,
}: {
  stay: Point;
  onClose: () => void;
  onSave: (p: Point) => void;
}) {
  const [point, setPoint] = useState(stay);
  return (
    <Modal title="Where do you stay?" onClose={onClose}>
      <p className={s.sub}>Drag the H marker to your hotel, homestay or station. Every day starts and ends here.</p>
      <div className={s.stayMap}>
        {/* centre on the saved stay (not the city centre) so the H marker is always in view */}
        <MapView center={stay} stay={point} onStayChange={(p) => setPoint({ ...p, label: point.label })} />
      </div>
      <Field label="Name">
        <input className={inputClass} value={point.label} onChange={(e) => setPoint({ ...point, label: e.target.value })} />
      </Field>
      <div className={s.actions}>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" onClick={() => onSave({ ...point, label: point.label.trim() || "Stay" })}>
          Use this place
        </Button>
      </div>
    </Modal>
  );
}
