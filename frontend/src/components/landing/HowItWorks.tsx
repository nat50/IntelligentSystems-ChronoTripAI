"use client";

import { useRef } from "react";
import { gsap, MEDIA, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

// Coordinates from Figma frame "03 · Itinerary" (map area 900 × 840)
const STAY = [207.3, 470.3];
const ROUTE = [
  [129.6, 618.5],
  [198.4, 573.2],
  [287.8, 526.3],
  [402.7, 420.7],
  [346.2, 301.2],
  [289.5, 337.7],
];
const ROUTE_D = "M207.3 470.3L129.6 618.5L198.4 573.2L287.8 526.3L402.7 420.7L346.2 301.2L289.5 337.7L207.3 470.3Z";
const IDLE = [
  [421, 212],
  [643, 224],
  [481.5, 326.7],
  [560, 520],
  [705, 420],
  [395, 655],
  [235, 245],
  [530, 150],
  [760, 610],
  [610, 690],
];
const TIMES = [
  ["08:15", "Market · Thu Thiem"],
  ["09:30", "Museum · An Khanh"],
  ["11:45", "Lunch · An Phu"],
  ["14:00", "Café · Phuoc Long B"],
  ["16:40", "Park · Binh Tho"],
  ["19:30", "Night market · Truong Tho"],
];
// a museum-like hour profile; 09:00–11:00 is the golden window
const PROFILE = [1, 1, 0, 0, 0, 1, 2, 4, 8, 14, 13, 9, 6, 6, 7, 8, 6, 4, 3, 2, 1, 1, 1, 1];

const pct = ([x, y]: number[]) => ({ left: `${(x / 900) * 100}%`, top: `${(y / 840) * 100}%` });

const STEPS = [
  {
    title: "Pick the places",
    text: "Tap up to 30 places on the map — or let ChronoTrip suggest the best-rated ones. Set 1 to 3 days, your hours and your pace.",
  },
  {
    title: "We estimate each place",
    text: "Models trained on millions of check-ins predict how good a place is, how long people stay, when it's open and its golden hour. Always labelled as estimates.",
  },
  {
    title: "We order your day",
    text: "A memetic genetic algorithm searches thousands of orders, respecting opening hours, meals and energy — then draws the route from your stay and back.",
  },
];

/** cumulative share of the route length at which each numbered pin is reached */
function arrivalShares() {
  const pts = [STAY, ...ROUTE, STAY];
  const seg = pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
  const total = seg.reduce((a, b) => a + b, 0);
  let acc = 0;
  return ROUTE.map((_, i) => (acc += seg[i]) / total);
}

export function HowItWorks() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, desktop: MEDIA.desktop }, (ctx) => {
        const { motion, desktop } = ctx.conditions as { motion: boolean; desktop: boolean };
        if (!motion) return;
        const q = gsap.utils.selector(root);
        const steps = q(".js-step");
        const sel = q(".js-sel");
        const nums = q(".js-num");
        const rows = q(".js-tl-row");
        const shares = arrivalShares();

        gsap.set(steps.slice(1), { autoAlpha: 0.3 });
        gsap.set(q(".js-idle, .js-sel"), { autoAlpha: 0, y: -30 });
        gsap.set(sel, { backgroundColor: "#9aa0a6" });
        gsap.set(q(".js-card"), { autoAlpha: 0, scale: 0.85, y: 20 });
        gsap.set(q(".js-hour"), { scaleY: 0 });
        gsap.set(q(".js-route"), { drawSVG: "0%" });
        gsap.set([...nums, q(".js-stay")[0]], { autoAlpha: 0, scale: 0 });
        gsap.set(q(".js-timeline"), { autoAlpha: 0, x: 40 });
        gsap.set(rows, { autoAlpha: 0, x: 16 });

        const tl = gsap.timeline({
          defaults: { ease: "power2.out" },
          scrollTrigger: desktop
            ? {
                trigger: q(".js-pin")[0],
                start: "top top",
                end: "+=320%",
                scrub: 1,
                pin: true,
                anticipatePin: 1,
                snap: { snapTo: "labelsDirectional", duration: { min: 0.25, max: 0.8 }, ease: "power1.inOut", delay: 0.05 },
              }
            : { trigger: q(".js-board")[0], start: "top 70%", toggleActions: "play none none reverse" },
        });

        // step 1 — pins drop in, six get picked
        tl.addLabel("s1")
          .to(q(".js-bar-fill"), { scaleY: 1 / 3, ease: "none", duration: 1 }, "s1")
          .to(q(".js-idle, .js-sel"), { autoAlpha: 1, y: 0, ease: "back.out(2.2)", duration: 0.5, stagger: 0.03 }, "s1")
          .to(sel, { backgroundColor: "#d6336c", scale: 1.25, duration: 0.3, stagger: 0.06 }, "s1+=0.55")
          // step 2 — a place card with its learned hour profile
          .addLabel("s2", "+=0.25")
          .to(steps[0], { autoAlpha: 0.3, duration: 0.2 }, "s2")
          .to(steps[1], { autoAlpha: 1, duration: 0.2 }, "s2")
          .to(q(".js-bar-fill"), { scaleY: 2 / 3, ease: "none", duration: 1 }, "s2")
          .to(q(".js-card"), { autoAlpha: 1, scale: 1, y: 0, ease: "back.out(1.6)", duration: 0.45 }, "s2")
          .to(q(".js-hour"), { scaleY: 1, stagger: 0.015, duration: 0.3 }, "s2+=0.2")
          .fromTo(q(".js-golden"), { autoAlpha: 0, scale: 0.8 }, { autoAlpha: 1, scale: 1, duration: 0.25, stagger: 0.08 }, "s2+=0.6")
          // step 3 — the GA orders the day, the route is drawn from the stay
          .addLabel("s3", "+=0.35")
          .to(steps[1], { autoAlpha: 0.3, duration: 0.2 }, "s3")
          .to(steps[2], { autoAlpha: 1, duration: 0.2 }, "s3")
          .to(q(".js-bar-fill"), { scaleY: 1, ease: "none", duration: 1.2 }, "s3")
          .to(q(".js-card"), { autoAlpha: 0, scale: 0.9, y: -10, duration: 0.25 }, "s3")
          .to(q(".js-stay"), { autoAlpha: 1, scale: 1, ease: "back.out(2)", duration: 0.3 }, "s3")
          .to(q(".js-timeline"), { autoAlpha: 1, x: 0, duration: 0.35 }, "s3+=0.1")
          .to(q(".js-route"), { drawSVG: "100%", ease: "none", duration: 1.2 }, "s3+=0.15");
        nums.forEach((n, i) => {
          const at = `s3+=${0.15 + shares[i] * 1.2 - 0.05}`;
          tl.to(sel[i], { autoAlpha: 0, scale: 0.4, duration: 0.15 }, at)
            .to(n, { autoAlpha: 1, scale: 1, ease: "back.out(2.5)", duration: 0.25 }, at)
            .to(rows[i], { autoAlpha: 1, x: 0, duration: 0.25 }, at);
        });
        tl.addLabel("end", "+=0.3");
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} id="how" className={s.how} aria-labelledby="how-title">
      <div className={`${s.container} ${s.howPin} js-pin`}>
        <div className={s.steps}>
          <div className={s.stepsHeader}>
            <p className={s.eyebrow}>How it works</p>
            <h2 id="how-title" className={s.h2}>
              Three steps.
              <br />
              One good day.
            </h2>
          </div>
          <div className={s.stepList}>
            <span className={s.stepBar} aria-hidden>
              <span className={`${s.stepBarFill} js-bar-fill`} style={{ transform: "scaleY(1)" }} />
            </span>
            {STEPS.map((st, i) => (
              <div key={st.title} className={`${s.step} js-step`}>
                <span className={s.stepNum}>{i + 1}</span>
                <div>
                  <h3 className={s.stepTitle}>{st.title}</h3>
                  <p className={s.stepText}>{st.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className={`${s.board} js-board`} aria-hidden>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className={s.boardWards} src="/figma/thu-duc-wards-900x780.svg" width={900} height={780} alt="" />
          <svg className={s.boardRoute} viewBox="0 0 900 840" preserveAspectRatio="none">
            <path className="js-route" d={ROUTE_D} fill="none" stroke="#D6336C" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {IDLE.map((p) => (
            <span key={p.join()} className={`${s.pin} js-idle`} style={pct(p)} />
          ))}
          {ROUTE.map((p) => (
            <span key={p.join()} className={`${s.pin} ${s.pinSel} js-sel`} style={pct(p)} />
          ))}
          {ROUTE.map((p, i) => (
            <span key={`n${i}`} className={`${s.numPin} js-num`} style={pct(p)}>
              {i + 1}
            </span>
          ))}
          <span className={`${s.stay} js-stay`} style={pct(STAY)}>
            H
          </span>

          <div className={`${s.placeCard} js-card`}>
            <p className={s.placeCardTitle}>Museum · An Khanh</p>
            <p className={s.placeCardMeta}>~85 min · best 09:00–11:00</p>
            <div className={s.hours}>
              {PROFILE.map((v, h) => (
                <span
                  key={h}
                  className={`${s.hourBar} ${h === 9 || h === 10 ? s.hourGolden : ""} js-hour`}
                  style={{ height: `${(v / 14) * 100}%` }}
                />
              ))}
            </div>
            <div className={s.hourAxis}>
              <span>00</span>
              <span>06</span>
              <span>12</span>
              <span>18</span>
              <span>24</span>
            </div>
            <div className={s.placeCardTags}>
              <span className={`${s.tagGolden} js-golden`}>☀ Golden hour ×1.25</span>
              <span className={`${s.tagEst} js-golden`}>Estimated · high confidence</span>
            </div>
          </div>

          <div className={`${s.timeline} js-timeline`}>
            {TIMES.map(([t, name]) => (
              <div key={t} className={`${s.tlRow} js-tl-row`}>
                <strong>{t}</strong>
                <span className={s.tlDot} />
                <span>{name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
