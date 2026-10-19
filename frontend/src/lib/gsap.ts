"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { DrawSVGPlugin } from "gsap/DrawSVGPlugin";
import { Flip } from "gsap/Flip";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";

gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText, DrawSVGPlugin, Flip);
gsap.defaults({ ease: "power3.out", duration: 0.9 });

/** Media conditions shared by every landing section. */
export const MEDIA = {
  motion: "(prefers-reduced-motion: no-preference)",
  desktop: "(min-width: 900px) and (prefers-reduced-motion: no-preference)",
  mobile: "(max-width: 899px) and (prefers-reduced-motion: no-preference)",
  reduce: "(prefers-reduced-motion: reduce)",
} as const;

export { DrawSVGPlugin, Flip, gsap, ScrollTrigger, SplitText, useGSAP };
