"use client";

import { useEffect, useRef } from "react";
import { Nav } from "./nav";
import { Hero } from "./hero";
import { Mess } from "./mess";
import { Engine } from "./engine";
import { Result } from "./result";
import { Bento } from "./bento";
import { Marquee } from "./marquee";
import { Pricing } from "./pricing";
import { CtaBand, Footer } from "./cta-footer";

export function LandingPage() {
  const rootRef = useRef<HTMLDivElement>(null);

  // Arm reveal animations only once a real animation frame fires AND motion is
  // allowed. In a paint-stalled / reduced-motion context the page stays at its
  // visible base state instead of frozen-hidden.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const raf = requestAnimationFrame(() => root.classList.add("js-armed"));
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="theme-marketing" ref={rootRef}>
      <Nav />
      <main id="top">
        <Hero />
        <Mess />
        <Engine />
        <Result />
        <Bento />
        <Marquee />
        <Pricing />
        <CtaBand />
      </main>
      <Footer />
    </div>
  );
}
