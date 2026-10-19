"use client";

import Lenis from "lenis";
import { createContext, useContext, useEffect, useRef, type RefObject } from "react";
import { gsap, ScrollTrigger } from "@/lib/gsap";

const LenisContext = createContext<RefObject<Lenis | null> | null>(null);

/**
 * Inertia smooth scrolling for the landing page, driven by GSAP's ticker so
 * ScrollTrigger pins and scrubs stay frame-perfect. Disabled for reduced motion;
 * touch devices keep native scrolling (syncTouch off).
 */
export function SmoothScroll({ children }: { children: React.ReactNode }) {
  const lenis = useRef<Lenis | null>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const instance = new Lenis({ lerp: 0.09, wheelMultiplier: 0.9, smoothWheel: true, syncTouch: false });
    instance.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => instance.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    lenis.current = instance;
    // pins measure layout: refresh once fonts and images are in
    const refresh = () => ScrollTrigger.refresh();
    document.fonts?.ready.then(refresh);
    window.addEventListener("load", refresh);
    return () => {
      window.removeEventListener("load", refresh);
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      instance.destroy();
      lenis.current = null;
    };
  }, []);

  return <LenisContext.Provider value={lenis}>{children}</LenisContext.Provider>;
}

/** Smooth-scroll to an anchor (falls back to native scrolling). */
export function useScrollTo() {
  const lenis = useContext(LenisContext);
  return (target: string) => {
    const instance = lenis?.current;
    if (instance) instance.scrollTo(target, { duration: 1.6, easing: (t) => 1 - Math.pow(1 - t, 4) });
    else document.querySelector(target)?.scrollIntoView({ behavior: "smooth" });
  };
}
