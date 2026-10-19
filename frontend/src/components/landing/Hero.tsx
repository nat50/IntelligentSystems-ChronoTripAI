"use client";

import { useRef } from "react";
import { ButtonLink } from "@/components/ui";
import { gsap, MEDIA, SplitText, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

const DAY = [
  ["08:15", "Market · Thu Thiem"],
  ["09:30", "Museum · An Khanh"],
  ["11:45", "Lunch · An Phu"],
];

/**
 * Figma 01 · Landing. Three depth layers — Far (Vietnam), Mid (HCMC · Thu Duc),
 * Near (Day card) — each nested as  scroll-layer > pointer-layer > intro-layer
 * so the three animations never fight over the same transform.
 */
export function Hero() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, desktop: MEDIA.desktop }, (ctx) => {
        const { motion, desktop } = ctx.conditions as { motion: boolean; desktop: boolean };
        if (!motion) return;
        const q = gsap.utils.selector(root);

        // 1 · intro
        const intro = gsap.timeline({ defaults: { ease: "expo.out" }, delay: 0.1 });
        intro.from(q(".js-eyebrow"), { y: 16, autoAlpha: 0, duration: 0.8 });
        SplitText.create(q(".js-headline")[0], {
          type: "lines,chars",
          mask: "lines",
          linesClass: "line",
          autoSplit: true,
          onSplit: (self) =>
            intro.from(self.chars, { yPercent: 115, duration: 1.2, stagger: 0.016 }, 0.15),
        });
        intro
          .from(q(".js-fade"), { y: 26, autoAlpha: 0, duration: 1, stagger: 0.09 }, 0.55)
          .from(q(".js-far-in"), { y: 90, autoAlpha: 0, scale: 0.9, duration: 1.6 }, 0.2)
          .from(q(".js-mid-in"), { y: 120, autoAlpha: 0, rotation: -5, duration: 1.6 }, 0.35)
          .from(q(".js-near-in"), { y: 160, autoAlpha: 0, rotationX: 40, transformPerspective: 900, duration: 1.6 }, 0.55)
          .fromTo(
            q(".js-ping"),
            { scale: 0.4, autoAlpha: 0.9 },
            { scale: 2.8, autoAlpha: 0, duration: 1.6, repeat: 2, ease: "power2.out" },
            1.3,
          );

        // 2 · scroll parallax: far drifts slowest, the day card overtakes and tilts
        gsap
          .timeline({
            scrollTrigger: { trigger: root.current, start: "top top", end: "bottom top", scrub: 0.8 },
            defaults: { ease: "none" },
          })
          .to(q(".js-far"), { yPercent: desktop ? 34 : 14 }, 0)
          .to(q(".js-mid"), { yPercent: desktop ? 20 : 8 }, 0)
          .to(q(".js-near"), { yPercent: desktop ? -60 : -20, rotationX: 18, scale: 0.94, transformPerspective: 900 }, 0)
          .to(q(".js-copy"), { y: desktop ? 140 : 40, autoAlpha: 0.1, scale: 0.97 }, 0);

        // 3 · pointer parallax (desktop): depth-weighted drift
        if (!desktop) return;
        const layers = [
          { el: q(".js-far-tilt")[0], depth: 8 },
          { el: q(".js-mid-tilt")[0], depth: 18 },
          { el: q(".js-near-tilt")[0], depth: 32 },
        ].map(({ el, depth }) => ({
          depth,
          x: gsap.quickTo(el, "x", { duration: 1.1, ease: "power3.out" }),
          y: gsap.quickTo(el, "y", { duration: 1.1, ease: "power3.out" }),
        }));
        const tiltNear = gsap.quickTo(q(".js-near-tilt")[0], "rotationY", { duration: 1.1, ease: "power3.out" });
        const onMove = (e: PointerEvent) => {
          const nx = e.clientX / window.innerWidth - 0.5;
          const ny = e.clientY / window.innerHeight - 0.5;
          layers.forEach((l) => {
            l.x(-nx * l.depth * 2);
            l.y(-ny * l.depth * 1.4);
          });
          tiltNear(nx * 10);
        };
        window.addEventListener("pointermove", onMove);
        return () => window.removeEventListener("pointermove", onMove);
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} className={s.hero} aria-labelledby="hero-title">
      <div className={s.heroInner}>
        <div className={`${s.copy} js-copy`}>
          <p className={`${s.eyebrow} js-eyebrow`}>Itinerary planner</p>
          <h1 id="hero-title" className={`${s.headline} js-headline`}>
            Your day,
            <br />
            in the right order.
          </h1>
          <p className={`${s.lead} ${s.heroText} js-fade`}>
            Pick the places. ChronoTrip schedules them around opening hours, travel time and the best hour to visit.
          </p>
          <div className={`${s.ctaRow} js-fade`}>
            <ButtonLink href="/plan">Start planning</ButtonLink>
            <span className={s.proof}>Learned from 18M real check-ins</span>
          </div>
        </div>

        <div className={s.stage} aria-hidden>
          <div className={`${s.layer} ${s.far} js-far`}>
            <div className="js-far-tilt">
              <div className="js-far-in" style={{ position: "relative" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className={s.mapImg} src="/figma/vietnam-provinces.svg" width={270} height={450} alt="" />
                <span className={`${s.ping} js-ping`} />
                <span className={`${s.mapLabel} ${s.farLabel}`}>Vietnam</span>
              </div>
            </div>
          </div>
          <div className={`${s.layer} ${s.mid} js-mid`}>
            <div className="js-mid-tilt">
              <div className="js-mid-in" style={{ position: "relative" }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className={s.mapImg} src="/figma/hcmc-thu-duc.svg" width={440} height={440} alt="" />
                <span className={`${s.mapLabel} ${s.midLabel}`}>Ho Chi Minh City · Thu Duc</span>
              </div>
            </div>
          </div>
          <div className={`${s.layer} ${s.near} js-near`}>
            <div className="js-near-tilt">
              <div className={`${s.dayCard} js-near-in`}>
                <div className={s.dayCardHead}>
                  <span className={s.dayCardTitle}>Day 1</span>
                  <span className={s.dayCardMeta}>6 stops</span>
                </div>
                {DAY.map(([t, name]) => (
                  <div key={t} className={s.dayRow}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src="/figma/dot-8.svg" width={8} height={8} alt="" />
                    <strong>{t}</strong>
                    <span>{name}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className={s.scrollHint} aria-hidden>
        Scroll
        <span className={s.scrollLine} />
      </div>
    </section>
  );
}
