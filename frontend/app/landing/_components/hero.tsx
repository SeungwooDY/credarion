"use client";

import { useEffect, useRef } from "react";
import { Reveal, Ticker, prefersReducedMotion } from "./primitives";

export function Hero() {
  const fillRef = useRef<HTMLElement>(null);

  // Progress bar fills to 97.3% when scrolled into view.
  useEffect(() => {
    const el = fillRef.current;
    if (!el) return;
    const target = 97.3;
    if (prefersReducedMotion()) {
      el.style.right = `${100 - target}%`;
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            requestAnimationFrame(() => {
              el.style.right = `${100 - target}%`;
            });
            io.disconnect();
          }
        }
      },
      { threshold: 0.4 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="hero">
      <div className="ledger-bg" aria-hidden="true" />
      <div className="wrap">
        <div className="hero-grid">
          <div>
            <Reveal as="span" className="eyebrow">
              AI Accounting Co-pilot · Asia-Pacific
            </Reveal>
            <Reveal as="div" delay={1}>
              <h1 className="display">
                Supplier reconciliation,
                <br />
                resolved by morning.
              </h1>
            </Reveal>
            <Reveal as="div" delay={2}>
              <p className="lede">
                Credarion ingests messy ERP goods receipts and supplier
                statements in any format, matches every line, and flags only
                what truly doesn&apos;t — so seven days of spreadsheet work close
                in one.
              </p>
            </Reveal>
            <Reveal className="hero-cta" delay={3}>
              <a href="#demo" className="btn btn-ink">
                Book a demo <span className="arrow">→</span>
              </a>
              <a href="#engine" className="btn btn-ghost">
                See the engine
              </a>
            </Reveal>
            <Reveal className="hero-note" delay={4}>
              <span>
                <span className="dot dot-green" />
                Exact · Fuzzy · Multi-PO · AI
              </span>
              <span>
                <span className="dot dot-amber" />
                Audit-ready trail
              </span>
              <span>Kingdee · Yonyou · Xero · SAP</span>
            </Reveal>
          </div>

          <Reveal as="aside" className="readout" delay={2}>
            <div className="readout-head">
              <span className="cap">Auto-match rate</span>
              <span className="cap" style={{ color: "var(--ink-mute)" }}>
                Live · monthly close
              </span>
            </div>
            <div className="rate-block">
              <div className="rate-num">
                <Ticker to={97.3} dec={1} />
                <span className="pct">%</span>
              </div>
              <div className="rate-bar">
                <i ref={fillRef} />
              </div>
            </div>
            <div className="beforeafter">
              <div className="ba-cell">
                <div className="k">Manual close</div>
                <div className="v">
                  <Ticker to={7.0} dec={1} />d
                </div>
              </div>
              <div className="ba-arrow">→</div>
              <div className="ba-cell after">
                <div className="k">With Credarion</div>
                <div className="v">
                  <Ticker to={1.5} dec={1} />d
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
