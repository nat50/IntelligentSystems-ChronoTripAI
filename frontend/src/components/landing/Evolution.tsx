"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { cx } from "@/components/ui";
import { Flip, gsap, MEDIA, ScrollTrigger, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

// genes 1..12 belong to day 1/2/3 in the final plan; "|" separates days, the
// segment after the last separator is the reserve pool (spec III.4)
const DAY_OF: Record<string, number> = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1, 7: 1, 8: 1, 9: 2, 10: 2, 11: 2, 12: 3 };
const STAGES = [
  { gen: 0, label: "Random population", genes: "7 2 11 | 5 12 1 9 | 3 8 | 10 4 6" },
  { gen: 60, label: "Crossover + mutation", genes: "2 1 7 4 | 5 6 9 8 | 11 3 10 | 12" },
  { gen: 400, label: "After 2-opt / Or-opt", genes: "1 2 3 4 | 5 6 7 8 | 9 10 11 | 12" },
];
const COLORS = ["#d6336c", "#1a73e8", "#188038", "#9aa0a6"];

// fitness rising quickly then flattening
const CURVE = (() => {
  const pts = Array.from({ length: 41 }, (_, i) => {
    const x = (i / 40) * 400;
    const y = 120 - 105 * (1 - Math.exp(-i / 7)) - (i % 3 === 0 ? 0 : 2);
    return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  });
  return pts.join("");
})();

export function Evolution() {
  const root = useRef<HTMLElement>(null);
  const [stage, setStage] = useState(STAGES.length - 1);
  const flipState = useRef<ReturnType<typeof Flip.getState> | null>(null);
  // each gene with the segment (day, or 3 = reserve pool) it currently sits in
  const genes = useMemo(() => {
    let seg = 0;
    return STAGES[stage].genes.split(" ").map((g) => (g === "|" ? { g, seg: ++seg } : { g, seg }));
  }, [stage]);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        const q = gsap.utils.selector(root);
        setStage(0);
        gsap.fromTo(
          q(".js-curve"),
          { drawSVG: "0%" },
          { drawSVG: "100%", ease: "none", scrollTrigger: { trigger: q(".js-board")[0], start: "top 75%", end: "bottom 45%", scrub: 0.6 } },
        );
        const st = ScrollTrigger.create({
          trigger: q(".js-board")[0],
          start: "top 75%",
          end: "bottom 45%",
          onUpdate(self) {
            const next = Math.min(STAGES.length - 1, Math.floor(self.progress * STAGES.length));
            setStage((cur) => {
              if (cur !== next) flipState.current = Flip.getState(q(".js-gene"));
              return next;
            });
          },
        });
        gsap.from(q(".js-reveal"), { y: 30, autoAlpha: 0, stagger: 0.08, scrollTrigger: { trigger: root.current, start: "top 70%" } });
        return () => {
          st.kill();
          setStage(STAGES.length - 1);
        };
      });
    },
    { scope: root },
  );

  // animate genes from their previous positions
  useLayoutEffect(() => {
    if (!flipState.current) return;
    Flip.from(flipState.current, { duration: 0.7, ease: "power2.inOut", stagger: 0.015, absolute: true });
    flipState.current = null;
  }, [stage]);

  return (
    <section ref={root} className={s.evo} aria-labelledby="evo-title">
      <div className={cx(s.container, s.evoGrid)}>
        <div>
          <p className={cx(s.eyebrow, "js-reveal")}>Under the hood</p>
          <h2 id="evo-title" className={cx(s.h2, "js-reveal")} style={{ marginTop: 14 }}>
            Evolution does the ordering.
          </h2>
          <ul className={s.evoList}>
            <li className="js-reveal">
              <b>Population</b> 100 plans — 30% clustered by area, 70% random
            </li>
            <li className="js-reveal">
              <b>Selection</b> tournament of 4, best 5% always kept
            </li>
            <li className="js-reveal">
              <b>Crossover</b> lock-aware order crossover, p = 0.85
            </li>
            <li className="js-reveal">
              <b>Mutation</b> swap, inversion, shift-day, pool exchange, p = 0.15
            </li>
            <li className="js-reveal">
              <b>Local search</b> 2-opt and Or-opt with time windows, every 5 generations
            </li>
          </ul>
        </div>
        <div className={cx(s.evoBoard, "js-board")} aria-label="A chromosome evolving">
          <div className={s.genome}>
            {genes.map(({ g, seg }) =>
              g === "|" ? (
                <span key={`sep${seg}`} data-flip-id={`sep${seg}`} className={cx(s.sep, "js-gene")} />
              ) : (
                <span
                  key={g}
                  data-flip-id={`g${g}`}
                  className={cx(s.gene, "js-gene")}
                  style={{ background: COLORS[stage === STAGES.length - 1 ? DAY_OF[g] : Math.min(seg, 3)], opacity: seg >= 3 ? 0.55 : 1 }}
                >
                  {g}
                </span>
              ),
            )}
          </div>
          <div className={s.genomeMeta}>
            <span>{STAGES[stage].label}</span>
            <span>generation {STAGES[stage].gen}</span>
          </div>
          <svg className={s.curve} viewBox="0 0 400 130" role="img" aria-label="Fitness improves over generations">
            <line x1="0" y1="125" x2="400" y2="125" stroke="#e2e0e3" strokeWidth="2" />
            <path className="js-curve" d={CURVE} fill="none" stroke="#d6336c" strokeWidth="3" strokeLinecap="round" />
            <text x="0" y="10" fontSize="11" fill="#5e5a60">
              fitness F(X)
            </text>
          </svg>
        </div>
      </div>
    </section>
  );
}
