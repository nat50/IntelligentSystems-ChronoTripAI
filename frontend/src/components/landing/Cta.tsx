"use client";

import { useRef } from "react";
import { ButtonLink, cx } from "@/components/ui";
import { gsap, MEDIA, SplitText, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

export function Cta() {
  const root = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, desktop: MEDIA.desktop }, (ctx) => {
        const { motion, desktop } = ctx.conditions as { motion: boolean; desktop: boolean };
        if (!motion) return;
        const q = gsap.utils.selector(root);
        SplitText.create(q(".js-title")[0], {
          type: "words",
          autoSplit: true,
          onSplit: (self) =>
            gsap.from(self.words, {
              yPercent: 60,
              autoAlpha: 0,
              rotationX: -50,
              transformOrigin: "50% 100%",
              stagger: 0.08,
              scrollTrigger: { trigger: root.current, start: "top 75%", end: "top 25%", scrub: 0.8 },
            }),
        });
        gsap.from(q(".js-fade"), { y: 30, autoAlpha: 0, stagger: 0.1, scrollTrigger: { trigger: q(".js-title")[0], start: "bottom 80%" } });
        if (!desktop) return;
        // magnetic button
        const wrap = q(".js-magnet")[0] as HTMLElement;
        const x = gsap.quickTo(wrap, "x", { duration: 0.6, ease: "elastic.out(1, 0.4)" });
        const y = gsap.quickTo(wrap, "y", { duration: 0.6, ease: "elastic.out(1, 0.4)" });
        const move = (e: PointerEvent) => {
          const r = wrap.getBoundingClientRect();
          x((e.clientX - (r.left + r.width / 2)) * 0.35);
          y((e.clientY - (r.top + r.height / 2)) * 0.35);
        };
        const leave = () => {
          x(0);
          y(0);
        };
        wrap.addEventListener("pointermove", move);
        wrap.addEventListener("pointerleave", leave);
        return () => {
          wrap.removeEventListener("pointermove", move);
          wrap.removeEventListener("pointerleave", leave);
        };
      });
    },
    { scope: root },
  );

  return (
    <>
      <section ref={root} className={s.cta} aria-labelledby="cta-title">
        <div className={s.container}>
          <h2 id="cta-title" className={cx(s.ctaTitle, "js-title")} style={{ perspective: 600 }}>
            Your day,
            <br />
            in the right order.
          </h2>
          <p className={cx(s.lead, s.ctaText, "js-fade")}>
            Pick a few places in Ho Chi Minh City or Hanoi. ChronoTrip does the rest in a few seconds.
          </p>
          <div className={cx(s.magnetic, "js-magnet", "js-fade")} style={{ padding: 24, margin: -24 }}>
            <ButtonLink href="/plan">Start planning</ButtonLink>
          </div>
        </div>
      </section>
      <footer className={s.footer}>
        <div className={cx(s.container, s.footerGrid)}>
          <p>
            © ChronoTrip AI · Memetic GA-TOPTW on LBSN2Vec++.
            <br />
            Place attributes are model estimates, not official opening hours, ratings or prices.
          </p>
          <p>
            Data:{" "}
            <a href="https://data.4tu.nl/datasets/882bd9c5-5821-48b6-9b35-5c9551dd04ca" target="_blank" rel="noreferrer">
              LBSN2Vec++
            </a>{" "}
            — Dingqi Yang et al., WWW&apos;19; IEEE TKDE 2020 (CC BY 4.0).
            <br />
            Maps & routing: ©{" "}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
              OpenStreetMap
            </a>{" "}
            contributors, OSRM, OpenFreeMap.
          </p>
        </div>
      </footer>
    </>
  );
}
