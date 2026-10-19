"use client";

import { useRef } from "react";
import { cx } from "@/components/ui";
import { gsap, MEDIA, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

/** SVG arc on a 24-hour clock face (0:00 at the top). */
function arc(r: number, from: number, to: number) {
  const pt = (m: number) => {
    const a = (m / 1440) * 2 * Math.PI - Math.PI / 2;
    return [100 + r * Math.cos(a), 100 + r * Math.sin(a)];
  };
  const [x0, y0] = pt(from);
  const [x1, y1] = pt(to);
  const large = to - from > 720 ? 1 : 0;
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function Ring({ children }: { children?: React.ReactNode }) {
  return (
    <>
      <circle cx="100" cy="100" r="80" fill="none" stroke="#e2e0e3" strokeWidth="14" />
      {[0, 6, 12, 18].map((h) => {
        const a = (h / 24) * 2 * Math.PI - Math.PI / 2;
        return (
          <text key={h} x={100 + 54 * Math.cos(a)} y={104 + 54 * Math.sin(a)} textAnchor="middle" fontSize="11" fill="#5e5a60" fontWeight="600">
            {String(h).padStart(2, "0")}
          </text>
        );
      })}
      {children}
    </>
  );
}

const RULES = [
  {
    title: "Never a closed door",
    text: "Each place gets an opening window learned from when people actually check in — the hours that hold 90% of visits.",
    art: (
      <svg viewBox="0 0 200 200">
        <Ring>
          <path className="js-draw" d={arc(80, 8 * 60, 22 * 60)} fill="none" stroke="#d6336c" strokeWidth="14" strokeLinecap="round" />
          <g className={s.spin} style={{ animationDuration: "24s" }}>
            <line x1="100" y1="100" x2="100" y2="44" stroke="#1d1b1e" strokeWidth="4" strokeLinecap="round" />
          </g>
          <circle cx="100" cy="100" r="6" fill="#1d1b1e" />
        </Ring>
      </svg>
    ),
  },
  {
    title: "Golden hour × 1.25",
    text: "Every place has its best two hours. Arrive inside them and the stop counts 25% more in the plan's score.",
    art: (
      <svg viewBox="0 0 200 200">
        <g className={s.spin}>
          {Array.from({ length: 12 }, (_, i) => (
            <line
              key={i}
              x1="100"
              y1="30"
              x2="100"
              y2="48"
              stroke="#f3b04d"
              strokeWidth="6"
              strokeLinecap="round"
              transform={`rotate(${i * 30} 100 100)`}
            />
          ))}
        </g>
        <circle className="js-pop" cx="100" cy="100" r="38" fill="#fef3e2" stroke="#b06000" strokeWidth="5" />
        <text x="100" y="108" textAnchor="middle" fontSize="22" fontWeight="800" fill="#b06000">
          ×1.25
        </text>
      </svg>
    ),
  },
  {
    title: "Meals, on time",
    text: "Lunch 11:30–13:30 and dinner 18:00–20:30 always get a food stop or a 60-minute break. No hungry afternoons.",
    art: (
      <svg viewBox="0 0 200 200">
        <Ring>
          <path className="js-draw" d={arc(80, 690, 810)} fill="none" stroke="#b06000" strokeWidth="14" strokeLinecap="round" />
          <path className="js-draw" d={arc(80, 1080, 1230)} fill="none" stroke="#d6336c" strokeWidth="14" strokeLinecap="round" />
          <text x="100" y="112" textAnchor="middle" fontSize="34" className="js-pop">
            🍜
          </text>
        </Ring>
      </svg>
    ),
  },
  {
    title: "Easy on your legs",
    text: "Effort runs from 1 to 5 by place type. Two demanding stops (4–5) are never scheduled back to back.",
    art: (
      <svg viewBox="0 0 200 200">
        {[2, 5, 1, 4, 2, 5].map((e, i) => (
          <rect
            key={i}
            className="js-bar"
            x={18 + i * 29}
            y={170 - e * 26}
            width="20"
            height={e * 26}
            rx="6"
            fill={e >= 4 ? "#d6336c" : "#cfcdd3"}
            style={{ transformOrigin: `${28 + i * 29}px 170px` }}
          />
        ))}
        <line x1="12" y1="176" x2="188" y2="176" stroke="#e2e0e3" strokeWidth="3" strokeLinecap="round" />
      </svg>
    ),
  },
];

/** Pinned horizontal scroll of the four business rules (spec III.2). Grid on mobile / reduced motion. */
export function Rules() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.desktop, () => {
        const q = gsap.utils.selector(root);
        const section = root.current!;
        const track = q(".js-track")[0] as HTMLElement;
        section.classList.add(s.motionOn);
        const distance = () => track.scrollWidth - (window.innerWidth - (track.parentElement?.getBoundingClientRect().left ?? 0));
        const scroller = gsap.to(track, {
          x: () => -Math.max(0, distance()),
          ease: "none",
          scrollTrigger: {
            trigger: q(".js-pin")[0],
            start: "top top",
            end: () => `+=${Math.max(1, distance())}`,
            pin: true,
            scrub: 1,
            anticipatePin: 1,
            invalidateOnRefresh: true,
          },
        });
        q(".js-rule").forEach((card) => {
          const sub = gsap.utils.selector(card);
          gsap
            .timeline({
              scrollTrigger: { trigger: card, containerAnimation: scroller, start: "left 85%", toggleActions: "play none none reverse" },
            })
            .from(card, { rotate: 4, y: 40, autoAlpha: 0.3, duration: 0.7 })
            .from(sub(".js-draw"), { drawSVG: "0%", duration: 1, stagger: 0.15, ease: "power2.inOut" }, 0.1)
            .from(sub(".js-pop"), { scale: 0, transformOrigin: "50% 50%", ease: "back.out(2)", duration: 0.6 }, 0.3)
            .from(sub(".js-bar"), { scaleY: 0, stagger: 0.08, ease: "back.out(1.6)", duration: 0.5 }, 0.2);
        });
        return () => section.classList.remove(s.motionOn);
      });
      mm.add(MEDIA.mobile, () => {
        gsap.utils.toArray<HTMLElement>(root.current!.querySelectorAll(".js-rule")).forEach((card) =>
          gsap.from(card, { y: 40, autoAlpha: 0, duration: 0.8, scrollTrigger: { trigger: card, start: "top 85%" } }),
        );
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} className={s.rules} aria-labelledby="rules-title">
      <div className={cx(s.container, s.rulesPin, "js-pin")}>
        <div className={s.rulesHead}>
          <p className={s.eyebrow}>Rules it respects</p>
          <h2 id="rules-title" className={s.h2}>
            Real days have rules.
          </h2>
        </div>
        <div className={cx(s.track, "js-track")}>
          {RULES.map((r, i) => (
            <article key={r.title} className={cx(s.rule, "js-rule")}>
              <div>
                <p className={s.ruleNum}>0{i + 1}</p>
                <h3 className={s.ruleTitle}>{r.title}</h3>
                <p className={s.ruleText}>{r.text}</p>
              </div>
              <div className={s.ruleArt} aria-hidden>
                {r.art}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
