# Handoff: Credarion Marketing Landing Page

## Overview
A complete marketing landing page + visual theme for **Credarion**, an AI accounting co-pilot for Asia-Pacific mid-market companies. The hero capability is **automated supplier reconciliation**: ingest messy ERP goods-receipt (GRN) data and supplier statements arriving in 5+ formats, auto-match them through a 4-layer engine, and flag discrepancies — turning ~7 days of manual Excel work into ~1.5.

The organizing metaphor is **reconciliation**: messy, mismatched data on the left → resolved, perfectly aligned books on the right. The page is designed to *demonstrate* that transformation, not just describe it — its centerpiece is an animated data pipeline.

> ⚠️ **This is the MARKETING site theme only.** It is intentionally **light/editorial** and deliberately *unlike* the existing in-app dashboard (which is dark-on-light with a purple accent, `--color-accent: #6c3ce0`). Keep the purple dashboard theme for the authenticated product; use THIS theme for marketing pages only.

## About the Design Files
The files in this bundle are **design references created in HTML/CSS/vanilla-JS** — a prototype showing the intended look, motion, and behavior. They are **not meant to ship as-is**. The task is to **recreate this design in the existing codebase** — which is **Next.js 16 (App Router) + React 19 + Tailwind CSS v4** (see `frontend/package.json`) — using the project's established patterns (`@theme` tokens in `globals.css`, the `font-geist-sans` / `font-geist-mono` variables already wired up, component conventions, etc.).

Because the codebase already uses **Geist Sans + Geist Mono**, the type pairing in this design is already available — no new font setup needed.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, hairline system, and interactions are all intentional. Recreate the UI pixel-accurately. Exact hex values, type sizes, and motion specs are documented below and in `credarion/theme.css`.

---

## Design Tokens

All tokens live in `credarion/theme.css` under `:root`. Port them into the marketing surface — e.g. a scoped `@theme` block or a `.theme-marketing` wrapper — so they don't collide with the app's purple dashboard tokens.

### Color
| Token | Value | Use |
|---|---|---|
| `--paper` | `#FAFAF9` | Page background — warm "fresh ledger" off-white |
| `--paper-2` | `#F4F4F1` | Faint panel / alt fill / progress troughs |
| `--card` | `#FFFFFF` | Cards, panels, table surfaces |
| `--ink` | `#0A0A0A` | Primary text, dark buttons, rules-on-emphasis |
| `--ink-soft` | `#56554F` | Secondary text (warm grey) |
| `--ink-mute` | `#8B897F` | Tertiary / captions / labels |
| `--ink-faint` | `#B6B4A9` | Placeholders / em-dashes / disabled |
| `--matched` | `#15734A` | **Green = reconciled / matched** (the semantic anchor) |
| `--matched-2` | `#1C8A5A` | Brighter green for ticks/dots |
| `--matched-tint` | `#EDF4EF` | Green row wash |
| `--matched-line` | `#C5DECC` | Green hairline/border |
| `--review` | `#9A6510` | **Amber = discrepancy / needs review** |
| `--review-2` | `#B27D17` | Brighter amber |
| `--review-tint` | `#F8F1E2` | Amber wash |
| `--review-line` | `#E6D4AC` | Amber border |
| `--alert` | `#A12017` | Red — used **very sparingly** (true errors only) |
| `--alert-tint` | `#F8ECEA` | Red wash |

**Hairlines (ruled-paper system — alignment IS the brand):**
`--rule: rgba(10,10,10,0.10)` · `--rule-2: rgba(10,10,10,0.16)` · `--rule-strong: rgba(10,10,10,0.26)` · `--grid-line: rgba(10,10,10,0.035)` (the faint background ledger grid).

**Color rules:** No decorative gradients. No purple/blue. Functional colors (green/amber/red) carry the whole palette — green and amber should only appear where they mean "matched" and "needs review." Everything else is ink + paper + hairlines.

### Typography
- **Sans (headings + body):** Geist — `--sans: "Geist", system-ui, …`
- **Mono (ALL numbers, PO refs, deltas, data, labels, eyebrows):** Geist Mono — `--mono: "Geist Mono", "JetBrains Mono", …`
- Numbers use **tabular figures + slashed zero**: `font-variant-numeric: tabular-nums slashed-zero;` and `font-feature-settings: "tnum","zero";`. This is essential — figures must align in columns and read like a precision readout.

| Class | Size (clamp) | Weight | Tracking | Line-height |
|---|---|---|---|---|
| `.display` (hero) | `clamp(40px, 6.4vw, 84px)` | 600 | `-0.035em` | 0.98 |
| `.h-sec` (section titles) | `clamp(30px, 4vw, 52px)` | 600 | `-0.03em` | 1.04 |
| `.h-sub` | `clamp(20px, 2.1vw, 26px)` | 540 | `-0.02em` | 1.2 |
| `.lede` (intro paragraph) | `clamp(17px, 1.35vw, 20px)` | 400 | — | 1.5, color `--ink-soft`, `max-width: 54ch` |
| `.eyebrow` / `.cap` (mono labels) | 11.5–12px | mono | `0.16–0.2em`, uppercase | — |
| Body base | 17px | 400 | — | 1.55 |

Eyebrow pattern: a mono uppercase label preceded by a 28px hairline, with the section index (e.g. `01`) tinted `--matched`. See `.eyebrow` in `theme.css`.

### Spacing / Layout
- Container: `max-width: 1240px` (`--maxw`), inline padding `clamp(20px, 5vw, 64px)` (`--gutter`).
- Vertical section rhythm: `padding-block: clamp(72px, 11vh, 140px)` (`--pad-section`).
- Sections separated by **1px hairline** top borders (`.rule-top`) — like ruled ledger paper.
- Strict, asymmetric Swiss grid with generous whitespace. Hero is `1.18fr / 0.82fr`; "the mess" and bento use defined column spans (see below).
- No border-radius anywhere — crisp square edges throughout (this is deliberate; do **not** add rounded corners).

### Motion (mechanical, never bouncy)
- `--snap: 360ms cubic-bezier(.16,.84,.28,1)` — the "click into alignment" easing
- `--snap-fast: 240ms cubic-bezier(.2,.9,.3,1)`
- `--ease: 320ms cubic-bezier(.4,0,.2,1)`
- Reveal-on-scroll: opacity + 14px translateY, 0.7s `cubic-bezier(.2,.7,.2,1)`, small stagger delays (`.d1`–`.d4` = 0.06–0.24s).
- Counters tick up with an ease-out cubic over ~1.3s.
- Respect `prefers-reduced-motion: reduce` (all animation/transition disabled; content shown at end-state).

---

## Screens / Views
Single long-scroll landing page. Sections in order (the page deliberately walks through the reconciliation process):

### 1. Nav (`.nav`)
- Sticky, 60px tall, translucent paper background w/ blur, 1px bottom hairline.
- Left: logo mark (inline SVG — a square with two short offset hairlines on the left resolving into one aligned green-ticked line on the right; it literally draws the reconciliation metaphor) + `CREDARION` wordmark (600, `letter-spacing: 0.18em`, uppercase).
- Center: nav links (`The problem`, `The engine`, `Results`, `Pricing`) — 14px, `--ink-soft`, animated underline on hover.
- Right: a mono status pill `● 97.3% reconciled` (green dot) + a primary dark button **Book a demo**.

### 2. Hero (`.hero`)
- Two-column grid (`1.18fr / 0.82fr`), bottom-aligned, over a faint radial-masked ledger grid (`.ledger-bg`).
- Left: eyebrow `AI Accounting Co-pilot · Asia-Pacific` → `.display` headline **"Supplier reconciliation, resolved by morning."** → `.lede` → two CTAs (`Book a demo` dark, `See the engine` ghost) → a mono micro-note row.
- Right: a **data readout panel** (`.readout`, 1px `--ink` border):
  - Header row: `AUTO-MATCH RATE` / `LIVE · MONTHLY CLOSE` (hairline under).
  - Big green tabular figure **`97.3%`** (`clamp(52px,6vw,76px)`, mono, `-0.04em`) that **counts up from 0** on load; a thin progress bar fills to 97.3% beneath it.
  - A before→after row: `MANUAL CLOSE 7.0d` `→` `WITH CREDARION 1.5d` (after value green). Both figures tick up.

### 3. The Mess (`#mess`) — the problem
- Eyebrow `01 — The Mess`, `.h-sec` title, `.lede`.
- Left: `.fan` — 5 overlapping, slightly-rotated supplier-statement cards (`.stmt`), **each in a visibly different layout**: different header positions, different column names for the same field, different languages (`采购订单` / `Order Ref` / `P/O #` / `Purchase Order` / `เลขที่ PO`), different formats (xlsx/csv/pdf/xls/scan), and the friction details (`428759.0` vs `PO428759` vs `4 28759`, blank PO cells). Cards rotate flat + lift on hover (positions/rotation applied by `site.js` from `data-rot/x/y/z` attrs).
- Right: `.friction-list` — 5 hairline-separated rows numbered `·01`–`·05`, each a title + description with inline mono `<code>` chips showing the exact data friction.

### 4. The Engine (`#engine`) — THE CENTERPIECE
The signature animated pipeline. A 3-column board (`.engine`, 1px `--ink` border, grid `0.96fr / 1.18fr / 1.06fr`):
- **LEFT — Sources** (`#col-src`): "ERP · Goods Receipts (GRN)" (filled ink square marker) + the 5 supplier feeds, each with a mono format badge. A **Re-run match ↻** ghost button restarts the animation.
- **MIDDLE — Matching engine** (`#col-gates`): 4 stacked **gates** (`.gate`), each with an index chip, name, mono sub-label, a live count, and a thin fill bar:
  1. **Exact Match** — `PO + part number`
  2. **Fuzzy Match** — `Normalized keys · trailing .0`
  3. **Multi-PO** — `Aggregated deliveries`
  4. **AI Fallback** — `Flagged for human review` (amber, `.gate.ai`)
- **RIGHT — Reconciled ledger** (`#col-ledger`): a big green tally `29 / 30 lines`, a live-appending list of matched rows (`.lrow`, mono, green ✓), and an amber **Discrepancy report** card at the end: *"1 line on Bangkok Polymer statement (PO 428804 · 180 units) has no matching ERP receipt — flagged for review."*

**Animation (see `engine.js` for the authoritative logic):**
- An SVG overlay (`#beams`) draws curved connector beams from each source → gate-1 entry, and from the gate stack → ledger. A subset are animated "flow" beams (green, dashed, `stroke-dashoffset` loop).
- 30 "tokens" (small mono PO pills) stream from the sources. Each travels to gate 1 and **snaps** through gates until it resolves, then snaps into the ledger.
- **Distribution: ~80% resolve at Exact (24), 4 at Fuzzy, 1 at Multi-PO, 1 reaches AI Fallback → amber "human review."** Tokens turn green (or amber) with a small "pop" scale at resolution; gate counts, bars, and the ledger tally tick up live; the discrepancy card appears when the amber token resolves.
- Triggered when the section scrolls into view; re-runnable via the button.
- Below the board: a legend (green "reconciled ~80% exact" / amber "human review <2%" / "18,420 lines / monthly cycle") + a green **Run it on your data** CTA.

### 5. The Result (`#result`)
- Eyebrow `03 — The Result`, `.h-sec` title.
- A 4-up `.stat-row` of big mono tabular figures (hairline-separated columns): **97.3%** auto-match (green, ticks up) · **7.0 → 1.5 d** close time · **18,420** lines reconciled (ticks up) · **1.1%** flagged (amber).
- A reconciled-ledger snippet table (`.recon-table`): 4 matched rows (green left-border inset, `Matched` green pill) + 1 flagged row (amber left-border, amber tinted bg, `Not in ERP` amber pill). Columns: PO Number · Part · Layer · ERP Qty · Stmt Qty · Amount ¥ · Status.

### 6. Capabilities bento (`.bento`)
- Eyebrow `Beyond reconciliation`, `.h-sec` title.
- 6-col grid of cells (1px hairline gaps): **Bank reconciliation** (w3), **Multi-entity consolidation** (w3), **Cash forecasting** (w2), **Statement ingestion** (w2), **Audit-ready trail** (w2). Each cell: mono `/ slug` label, title (bottom-anchored), short copy, optional green mono metric. Cells lighten to `--paper-2` on hover.

### 7. Supported-systems marquee (`.marquee`)
- A single hairline-bordered band; slow horizontal auto-scroll (38s linear loop, pauses on hover). Items populated by `site.js` from a `SYSTEMS` array: Kingdee 金蝶, Yonyou 用友, SAP, Oracle NetSuite, Xero, QuickBooks, MYOB, Sage, Microsoft Dynamics, HSBC, DBS, Wise — each a name + faint mono tag, hairline-separated.

### 8. Pricing (`#pricing`)
- Eyebrow `Pricing`, `.h-sec` title.
- 3 tiers (1px hairline gaps): **Close** `$490 / entity·mo`, **Consolidate** `$1,290 / entity·mo` (featured — inverted dark `--ink` card, amber tier label, green CTA), **Enterprise** `Custom`. Mono prices; green (or amber on dark) check bullets; CTA pinned to bottom.

### 9. CTA band (`#demo`) + Footer (`.foot`)
- CTA band over the ledger grid: `.display` **"Close your next period in a day, not a week."** + centered CTAs.
- Footer: logo + tagline, 3 link columns (Product / Company / Connect), hairline bottom bar with mono copyright + `● All systems reconciled`.

---

## Interactions & Behavior
- **Reveal-on-scroll:** elements with `.reveal` (+ optional `.d1`–`.d4` stagger) fade/slide up when entering the viewport. *Implementation note:* base state is the **visible** end-state; the hidden pre-animation state is gated behind an `html.js-armed` class added on the first `requestAnimationFrame` **and** `@media (prefers-reduced-motion: no-preference)`. This guarantees content is visible for SSR/no-JS/print/reduced-motion. In React, replicate with an IntersectionObserver hook, but keep the "visible unless JS armed AND motion allowed" fallback so nothing is ever stuck hidden.
- **Number tickers:** `.ticker[data-to][data-dec]` count from 0 to the target (ease-out cubic, ~1.3s) when scrolled into view. The base HTML carries the *final* value as text so no-JS/print shows the real number.
- **Engine:** auto-runs on scroll-into-view; **Re-run match ↻** restarts; tokens snap through gates; counters/bars/ledger update live. Full logic in `engine.js`.
- **Statement fan:** hover straightens + lifts the hovered card and raises its z-index.
- **Marquee:** infinite scroll, pauses on hover.
- **Nav links / underlines, button hover states, arrow nudges:** see `.btn`, `.nav-links a` in CSS.
- **Responsive:** at ≤940px the hero, mess, and engine collapse to single column (the engine's beams/tokens are hidden on mobile and gates stack); bento → 2-col; pricing → 1-col. At ≤560px stats and bento go single-column and the before/after stacks. Breakpoints in `sections.css`.

## State Management
For a React implementation, the only real runtime state is the engine animation:
- `engineState`: `idle | running | done`; per-gate counts `[exact, fuzzy, multiPo, ai]`; running `tally` and `processed`; a list of resolved ledger rows; `showDiscrepancy` boolean.
- Token stream can be modeled as a timed sequence (spawn every ~150ms) where each token has a `targetGate` drawn from the distribution `[24,4,1,1]`. Prefer driving the token positions with `requestAnimationFrame` / CSS transforms exactly as `engine.js` does, or a small state machine — but keep motion mechanical (snap easing), and gate it on reduced-motion + in-view.
- Tickers and reveals are view-triggered side-effects, not persistent state.
- No data fetching in the prototype — all figures are static marketing content. If wired to live stats later, the readout/stat figures are the natural binding points.

## Assets
- **No raster images or stock photography** (by design — "the only decoration is data itself").
- **Logo mark:** inline SVG, defined directly in the HTML (nav + footer). Reuse as a component.
- **Icons:** inline SVG only (checkmarks/flags in the ledger, the section arrow glyphs). No icon library required.
- **Fonts:** Geist + Geist Mono — already present in the codebase via `next/font` (`--font-geist-sans`, `--font-geist-mono`). The prototype loads them from Google Fonts; in the app, use the existing `next/font` setup instead.

## Files
In this bundle:
- `Credarion Landing Page.html` — the full landing page markup (open in a browser to see it live, including all animation).
- `credarion/theme.css` — design tokens, type scale, hairline system, buttons, badges, reveal logic. **Start here for tokens.**
- `credarion/sections.css` — all section/component layout & styling (nav, hero, mess, engine, result, bento, marquee, pricing, footer) + responsive breakpoints.
- `credarion/engine.js` — the authoritative reconciliation-pipeline animation (geometry, beams, token stream, distribution, counters).
- `credarion/site.js` — tickers, statement-fan layout, marquee population, reveal-on-scroll (with the rAF/reduced-motion-safe arming described above).

In the existing repo, the relevant context is `frontend/app/globals.css` (current `@theme` tokens + Geist font vars) and the product's real data vocabulary in `frontend/app/reconciliation/page.tsx` and `frontend/app/mismatches/page.tsx` (match types, discrepancy types, `¥` amounts, vendor codes, periods) — the marketing copy/figures were drawn from these to stay authentic.
