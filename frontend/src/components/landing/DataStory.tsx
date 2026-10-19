"use client";

import { useRef } from "react";
import { cx } from "@/components/ui";
import { gsap, MEDIA, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

// Spec Table 2 — measured on the raw LBSN2Vec++ files
const COUNTRIES = [
  ["Indonesia", 7_765_315],
  ["Malaysia", 4_926_144],
  ["Thailand", 2_633_608],
  ["Philippines", 1_998_063],
  ["Singapore", 871_619],
  ["Vietnam", 48_357],
] as const;
const SEA_TOTAL = 18_281_127;
const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

export function DataStory() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        const q = gsap.utils.selector(root);
        const counter = q(".js-counter")[0];
        const n = { v: 0 };
        gsap.to(n, {
          v: SEA_TOTAL,
          ease: "power1.out",
          onUpdate: () => (counter.textContent = fmt(n.v)),
          scrollTrigger: { trigger: root.current, start: "top 75%", end: "center 55%", scrub: 0.6 },
        });
        gsap.fromTo(
          q(".js-big"),
          { xPercent: 8 },
          { xPercent: -38, ease: "none", scrollTrigger: { trigger: root.current, start: "top bottom", end: "bottom top", scrub: true } },
        );
        gsap.from(q(".js-bar"), {
          scaleX: 0,
          stagger: 0.12,
          ease: "power2.out",
          scrollTrigger: { trigger: q(".js-bars")[0], start: "top 80%", end: "bottom 60%", scrub: 0.8 },
        });
        gsap.from(q(".js-reveal"), {
          y: 40,
          autoAlpha: 0,
          stagger: 0.1,
          scrollTrigger: { trigger: root.current, start: "top 70%" },
        });
      });
    },
    { scope: root },
  );

  const max = COUNTRIES[0][1];
  return (
    <section ref={root} className={s.data} aria-labelledby="data-title">
      <div className={`${s.bigNumber} js-big`} aria-hidden>
        18,281,127
      </div>
      <div className={cx(s.container, s.dataGrid)}>
        <div>
          <p className={cx(s.eyebrow, "js-reveal")}>Learned from real check-ins</p>
          <h2 id="data-title" className="visually-hidden">
            The data behind ChronoTrip
          </h2>
          <p className={cx(s.counter, "js-counter")} style={{ marginTop: 18 }}>
            {fmt(SEA_TOTAL)}
          </p>
          <p className={cx(s.counterLabel, "js-reveal")}>check-ins across Southeast Asia, Apr 2012 – Jan 2014</p>
          <div className={s.facts}>
            <div className={cx(s.fact, "js-reveal")}>
              <strong>90,048,627</strong>
              <span>check-ins worldwide</span>
            </div>
            <div className={cx(s.fact, "js-reveal")}>
              <strong>2,733,324</strong>
              <span>anonymous users</span>
            </div>
            <div className={cx(s.fact, "js-reveal")}>
              <strong>11,180,160</strong>
              <span>places</span>
            </div>
          </div>
        </div>
        <div>
          <div className={cx(s.dataBars, "js-bars")}>
            {COUNTRIES.map(([name, v]) => (
              <div key={name} className={cx(s.dataRow, name === "Vietnam" && s.dataVn)}>
                <span className={s.dataCountry}>{name}</span>
                <span className={s.dataTrack}>
                  <span
                    className={cx(s.dataBar, name === "Vietnam" && s.dataBarVn, "js-bar")}
                    style={{ width: `${(78 * v) / max}%` }}
                  />
                  <span className={s.dataValue}>{fmt(v)}</span>
                </span>
              </div>
            ))}
          </div>
          <p className={cx(s.dataNote, "js-reveal")}>
            Vietnam is sparse — so M1, M2 and M3 are trained on the whole region and applied to Ho Chi Minh City and
            Hanoi, each estimate tagged with its confidence. Dataset: LBSN2Vec++ (Dingqi Yang et al.), CC BY 4.0.
          </p>
        </div>
      </div>
    </section>
  );
}
