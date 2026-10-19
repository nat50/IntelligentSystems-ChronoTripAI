"use client";

import { Cta } from "./Cta";
import { DataStory } from "./DataStory";
import { Evolution } from "./Evolution";
import { Hero } from "./Hero";
import { HowItWorks } from "./HowItWorks";
import { Journey } from "./Journey";
import s from "./landing.module.css";
import { Nav } from "./Nav";
import { Rules } from "./Rules";
import { SmoothScroll } from "./SmoothScroll";

export function Landing() {
  return (
    <SmoothScroll>
      <div className={s.page}>
        <Nav />
        <main>
          <Hero />
          <Journey />
          <HowItWorks />
          <Rules />
          <DataStory />
          <Evolution />
        </main>
        <Cta />
      </div>
    </SmoothScroll>
  );
}
