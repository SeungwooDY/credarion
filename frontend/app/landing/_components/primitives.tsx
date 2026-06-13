"use client";

import { useEffect, useRef } from "react";

/* The reconciliation logo mark — two offset hairlines on the left resolving
   into one aligned, green-ticked line on the right. */
export function LogoMark() {
  return (
    <svg className="mark" viewBox="0 0 22 22" fill="none" aria-hidden="true">
      <rect x="0.5" y="0.5" width="21" height="21" stroke="#0A0A0A" />
      <line x1="4" y1="7" x2="11" y2="7" stroke="#8B897F" strokeWidth="1.4" />
      <line x1="6" y1="11" x2="11" y2="11" stroke="#8B897F" strokeWidth="1.4" />
      <line x1="11" y1="9" x2="18" y2="9" stroke="#15734A" strokeWidth="1.6" />
      <path
        d="M14.5 9 L11 12.5 L9 10.5"
        stroke="#15734A"
        strokeWidth="1.6"
        fill="none"
        strokeLinecap="square"
      />
    </svg>
  );
}

export function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/* Reveal-on-scroll wrapper. Base state is the VISIBLE end-state (so SSR / no-JS /
   reduced-motion always show content); the hidden pre-animation state only kicks
   in once the root is `.js-armed` AND motion is allowed (see marketing.css). */
export function Reveal({
  children,
  className = "",
  delay,
  as: Tag = "div",
  style,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: 1 | 2 | 3 | 4;
  as?: "div" | "span" | "aside" | "section";
  style?: React.CSSProperties;
}) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ref = useRef<any>(null);

  useEffect(() => {
    const el = ref.current as HTMLElement | null;
    if (!el) return;
    if (prefersReducedMotion()) {
      el.classList.add("in");
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        }
      },
      { threshold: 0.08, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const cls = ["reveal", delay ? `d${delay}` : "", className]
    .filter(Boolean)
    .join(" ");
  return (
    <Tag ref={ref} className={cls} style={style}>
      {children}
    </Tag>
  );
}

function formatNum(n: number, dec: number) {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  });
}

/* Counts up from 0 → `to` (ease-out cubic, ~1.3s) when scrolled into view.
   Renders the final value as text up-front so SSR/print/no-JS show the real
   number; the client drives the animation imperatively via the ref. */
export function Ticker({
  to,
  dec = 0,
  className = "",
}: {
  to: number;
  dec?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (prefersReducedMotion()) {
      el.textContent = formatNum(to, dec);
      return;
    }
    let raf = 0;
    let started = false;
    const animate = () => {
      const dur = 1300;
      let t0: number | null = null;
      const step = (ts: number) => {
        if (t0 === null) t0 = ts;
        const p = Math.min(1, (ts - t0) / dur);
        const e = 1 - Math.pow(1 - p, 3);
        el.textContent = formatNum(to * e, dec);
        if (p < 1) raf = requestAnimationFrame(step);
        else el.textContent = formatNum(to, dec);
      };
      raf = requestAnimationFrame(step);
    };
    const io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (en.isIntersecting && !started) {
            started = true;
            animate();
            io.disconnect();
          }
        }
      },
      { threshold: 0.4 }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [to, dec]);

  return (
    <span ref={ref} className={className}>
      {formatNum(to, dec)}
    </span>
  );
}
