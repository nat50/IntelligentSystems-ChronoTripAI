"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { cx, Logo } from "@/components/ui";
import ui from "@/components/ui/ui.module.css";
import { gsap, ScrollTrigger, useGSAP } from "@/lib/gsap";
import s from "./landing.module.css";
import { useScrollTo } from "./SmoothScroll";

export function Nav() {
  const [hidden, setHidden] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const bar = useRef<HTMLDivElement>(null);
  const scrollTo = useScrollTo();

  useGSAP(() => {
    const setProgress = gsap.quickSetter(bar.current, "scaleX");
    const st = ScrollTrigger.create({
      start: 0,
      end: "max",
      onUpdate(self) {
        setProgress(self.progress);
        const y = self.scroll();
        setScrolled(y > 24);
        setHidden(self.direction === 1 && y > 320);
      },
    });
    return () => st.kill();
  });

  return (
    <header className={cx(s.nav, scrolled && s.navScrolled, hidden && s.navHidden)}>
      <div className={cx(s.container, s.navInner)}>
        <Logo />
        <nav className={s.navLinks} aria-label="Main">
          <button type="button" className={cx(s.navLink, s.hideNarrow)} onClick={() => scrollTo("#how")}>
            How it works
          </button>
          <Link href="/admin" className={cx(s.navLink, s.hideMobile)}>
            Sign in
          </Link>
          <Link href="/plan" className={cx(ui.button, ui.primary, s.navCta)}>
            Start planning
          </Link>
        </nav>
      </div>
      <div ref={bar} className={s.progress} aria-hidden />
    </header>
  );
}
