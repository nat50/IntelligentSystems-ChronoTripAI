"use client";

import { useEffect, useRef, useState } from "react";
import { gsap, MEDIA, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";

const STEPS = [
  {
    title: "Vietnam",
    fact: (
      <>
        Only <b>48,357</b> check-ins — 160× fewer than Indonesia. So the models learn from all of Southeast Asia.
      </>
    ),
  },
  {
    title: "Ho Chi Minh City",
    fact: (
      <>
        <b>28,220</b> check-ins, the densest city in the Vietnamese data — with Hanoi, the scope of this prototype.
      </>
    ),
  },
  {
    title: "Thu Duc",
    fact: <>Real ward boundaries, real places. This is where your day starts.</>,
  },
];

const MAPS = [
  { src: "/figma/vietnam-provinces.svg", w: 270, h: 450, label: "Vietnam · provinces" },
  { src: "/figma/hcmc-thu-duc.svg", w: 440, h: 440, label: "Ho Chi Minh City · Thu Duc highlighted" },
  { src: "/figma/thu-duc-wards-900x780.svg", w: 900, h: 780, label: "Thu Duc · wards" },
];

/** Pinned zoom: Vietnam → HCMC (pink) → Thu Duc wards. Static row of three maps for reduced motion. */
export function Journey() {
  const root = useRef<HTMLElement>(null);
  const [motionReady, setMotionReady] = useState(false);

  // Render the accessible static version first. The pinned scene is a client-only
  // enhancement, so a slow or unavailable script can never stack all three steps.
  useEffect(() => {
    const media = window.matchMedia(MEDIA.motion);
    const syncMotion = () => setMotionReady(media.matches);
    syncMotion();
    media.addEventListener("change", syncMotion);
    return () => media.removeEventListener("change", syncMotion);
  }, []);

  useGSAP(
    () => {
      if (!motionReady) return;
      const mm = gsap.matchMedia();
      mm.add({ motion: MEDIA.motion, desktop: MEDIA.desktop }, (ctx) => {
        const { motion, desktop } = ctx.conditions as { motion: boolean; desktop: boolean };
        if (!motion) return;
        const q = gsap.utils.selector(root);
        const [vn, hcm, wards] = q(".js-map");
        const steps = q(".js-step");
        gsap.set([hcm, wards], { autoAlpha: 0 });
        gsap.set(steps.slice(1), { autoAlpha: 0, y: 50 });

        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: {
            trigger: q(".js-pin")[0],
            start: "top top",
            end: desktop ? "+=230%" : "+=160%",
            scrub: 1,
            pin: true,
            anticipatePin: 1,
          },
        });
        tl.from(vn, { scale: 0.82, autoAlpha: 0.4, duration: 0.35 })
          // dive into the pink HCMC dot on the Vietnam map
          .to(vn, { scale: 9, transformOrigin: "61.9% 82.9%", ease: "power2.in", duration: 1 })
          .to(vn, { autoAlpha: 0, duration: 0.25 }, "-=0.25")
          .fromTo(hcm, { scale: 0.3, autoAlpha: 0 }, { scale: 1, autoAlpha: 1, ease: "power2.out", duration: 0.55 }, "<")
          .to(steps[0], { autoAlpha: 0, y: -50, duration: 0.3 }, "<")
          .to(steps[1], { autoAlpha: 1, y: 0, duration: 0.3 }, ">-0.1")
          // then into the Thu Duc highlight
          .to(hcm, { scale: 5.5, transformOrigin: "37.5% 57%", ease: "power2.in", duration: 1 }, "+=0.35")
          .to(hcm, { autoAlpha: 0, duration: 0.25 }, "-=0.25")
          .fromTo(wards, { scale: 0.35, autoAlpha: 0 }, { scale: 1, autoAlpha: 1, ease: "power2.out", duration: 0.6 }, "<")
          .to(steps[1], { autoAlpha: 0, y: -50, duration: 0.3 }, "<")
          .to(steps[2], { autoAlpha: 1, y: 0, duration: 0.3 }, ">-0.1")
          .to(wards, { scale: 1.06, duration: 0.5 }, "+=0.1");
      });
    },
    { scope: root, dependencies: [motionReady], revertOnUpdate: true },
  );

  return (
    <section ref={root} className={s.journey} data-motion-ready={motionReady || undefined} aria-label="From Vietnam to your neighbourhood">
      <div className={`${s.journeyPin} js-pin`} data-motion-only>
        <div className={s.journeyMaps} aria-hidden>
          {MAPS.map((m) => (
            <div key={m.src} className={`${s.journeyMap} js-map`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={m.src} width={m.w} height={m.h} alt="" />
            </div>
          ))}
        </div>
        <div className={s.journeyText}>
          {STEPS.map((st, i) => (
            <div key={st.title} className={`${s.journeyStep} js-step`}>
              <p className={s.eyebrow}>Zooming in · {i + 1}/3</p>
              <h2 className={s.journeyTitle}>{st.title}</h2>
              <p className={s.journeyFact}>{st.fact}</p>
            </div>
          ))}
        </div>
      </div>

      <div className={`${s.container} ${s.journeyStatic}`} data-static-only>
        {MAPS.map((m, i) => (
          <figure key={m.src}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={m.src} width={m.w} height={m.h} alt={m.label} />
            <figcaption>
              <h2 className={s.stepTitle}>{STEPS[i].title}</h2>
              <p className={s.stepText}>{STEPS[i].fact}</p>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
