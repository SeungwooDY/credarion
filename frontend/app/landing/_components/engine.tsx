"use client";

import { useEffect, useRef } from "react";
import { Reveal } from "./primitives";

const GATES = [
  { idx: "1", name: "Exact Match", sub: "PO + part number" },
  { idx: "2", name: "Fuzzy Match", sub: "Normalized keys · trailing .0" },
  { idx: "3", name: "Multi-PO", sub: "Aggregated deliveries" },
  { idx: "4", name: "AI Fallback", sub: "Flagged for human review", ai: true },
];

const SOURCES = [
  { n: "ERP · Goods Receipts", m: "GRN", erp: true },
  { n: "Shenzhen Ruiyang", m: "xlsx" },
  { n: "Acme Components", m: "csv" },
  { n: "Tan Seng Metals", m: "pdf" },
  { n: "Yongtai Industrial", m: "xls" },
  { n: "Bangkok Polymer", m: "scan" },
];

export function Engine() {
  const boardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const board = boardRef.current;
    if (!board) return;

    const beamsEl = board.querySelector<SVGSVGElement>(".beams")!;
    const tokensEl = board.querySelector<HTMLDivElement>(".tokens")!;
    const ledgerRows = board.querySelector<HTMLDivElement>(".ledger-rows")!;
    const discrep = board.querySelector<HTMLDivElement>(".discrep")!;
    const runBtn = board.querySelector<HTMLButtonElement>(".run-btn")!;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ---- timeout bookkeeping so we can fully tear down on unmount ----------
    const timers = new Set<number>();
    const after = (fn: () => void, ms: number) => {
      const id = window.setTimeout(() => {
        timers.delete(id);
        fn();
      }, ms);
      timers.add(id);
      return id;
    };

    // ---- distribution: where each row resolves ----------------------------
    let PLAN: number[] = [];
    function buildPlan() {
      PLAN = [];
      const spec: [number, number][] = [[0, 24], [1, 4], [2, 1], [3, 1]];
      spec.forEach((s) => {
        for (let i = 0; i < s[1]; i++) PLAN.push(s[0]);
      });
      for (let k = PLAN.length - 1; k > 0; k--) {
        if (PLAN[k] === 0) {
          const j = Math.floor(Math.random() * (k + 1));
          if (PLAN[j] === 0) {
            const t = PLAN[k];
            PLAN[k] = PLAN[j];
            PLAN[j] = t;
          }
        }
      }
    }

    const TOTAL = 30;
    const GATE_MAX = [24, 4, 1, 1];

    const POOL = ["428759", "428760", "428762", "428765", "428771", "428780",
      "428781", "428790", "428803", "428804", "429001", "429014", "429022",
      "429038", "429041", "429055", "429067", "429072", "429088", "429090"];
    const po = (i: number) => "PO-" + POOL[i % POOL.length];
    const amt = () =>
      (Math.random() * 5000 + 400).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");

    // ---- geometry ---------------------------------------------------------
    type P = { x: number; y: number };
    const G: {
      src: P[];
      gate: P[];
      gateIn: P[];
      gateRight: number;
      ledger: P;
    } = { src: [], gate: [], gateIn: [], gateRight: 0, ledger: { x: 0, y: 0 } };

    function pt(el: Element | null) {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      const r = board!.getBoundingClientRect();
      return {
        x: b.left - r.left + b.width / 2,
        y: b.top - r.top + b.height / 2,
        right: b.right - r.left,
        left: b.left - r.left,
      };
    }
    function measure() {
      G.src = [];
      board!.querySelectorAll(".src-anchor").forEach((s) => {
        const p = pt(s);
        if (p) G.src.push({ x: p.x, y: p.y });
      });
      G.gate = [];
      G.gateIn = [];
      for (let i = 0; i < 4; i++) {
        const ge = board!.querySelector('.gate[data-gate="' + i + '"]');
        const pc = pt(ge);
        if (!pc) continue;
        G.gate.push({ x: pc.x, y: pc.y });
        G.gateIn.push({ x: pc.left, y: pc.y });
        G.gateRight = pc.right;
      }
      const led = board!.querySelector("[data-ledger]");
      const lp = pt(led);
      G.ledger = lp
        ? { x: lp.x, y: lp.y }
        : { x: (G.gate[0]?.x || 0) + 240, y: G.gate[0]?.y || 0 };
    }

    // ---- beams (SVG) ------------------------------------------------------
    function curve(a: P, b: P, k: number) {
      k = k || 0.5;
      const mx = a.x + (b.x - a.x) * k;
      return "M " + a.x + " " + a.y + " C " + mx + " " + a.y + " " + mx + " " + b.y + " " + b.x + " " + b.y;
    }
    function drawBeams() {
      if (reduce || !G.src.length || !G.gateIn.length) return;
      const w = board!.clientWidth;
      const h = board!.clientHeight;
      beamsEl.setAttribute("viewBox", "0 0 " + w + " " + h);
      let html = "";
      const entry = G.gateIn[0];
      G.src.forEach((s) => {
        html += '<path class="beam" d="' + curve({ x: s.x + 4, y: s.y }, entry, 0.55) + '"/>';
      });
      html += '<path class="beam-flow" d="' + curve({ x: G.src[0].x + 4, y: G.src[0].y }, entry, 0.55) + '"/>';
      html += '<path class="beam-flow" d="' + curve({ x: G.src[3].x + 4, y: G.src[3].y }, entry, 0.55) + '"/>';
      const gx = G.gateRight;
      [0, 1, 2].forEach((i) => {
        html += '<path class="beam" d="' + curve({ x: gx, y: G.gate[i].y }, G.ledger, 0.5) + '"/>';
      });
      html += '<path class="beam-flow" d="' + curve({ x: gx, y: G.gate[0].y }, G.ledger, 0.5) + '"/>';
      beamsEl.innerHTML = html;
    }

    // ---- counters ---------------------------------------------------------
    let gc = [0, 0, 0, 0];
    let tally = 0;
    let processed = 0;
    function setText(sel: string, v: string) {
      const e = board!.querySelector(sel);
      if (e) e.textContent = v;
    }
    function refreshCounts() {
      for (let i = 0; i < 4; i++) {
        const c = board!.querySelector('[data-gc="' + i + '"]');
        if (c) c.textContent = String(gc[i]);
        const fill = Math.min(1, gc[i] / GATE_MAX[i]);
        const bar = board!.querySelector<HTMLElement>('[data-gbar="' + i + '"]');
        if (bar) bar.style.right = 100 - fill * 100 + "%";
      }
      setText("[data-tally]", String(tally));
      setText("[data-total]", String(processed));
      setText(".gate-progress", processed + " / " + TOTAL);
    }

    // ---- ledger rows ------------------------------------------------------
    const TICK = '<svg class="tick" viewBox="0 0 12 12" fill="none"><path d="M2.5 6.2 5 8.7 9.6 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="square"/></svg>';
    const FLAG = '<svg class="tick" viewBox="0 0 12 12" fill="none"><path d="M6 1.5 V8 M6 10.4 v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1"/></svg>';
    function addLedgerRow(label: string, amber: boolean) {
      const row = document.createElement("div");
      row.className = "lrow" + (amber ? " amber" : "");
      row.innerHTML =
        '<span class="po">' + label + '</span><span class="amt">¥' + amt() + "</span>" +
        '<span class="st">' + (amber ? FLAG : TICK) + (amber ? "review" : "matched") + "</span>";
      ledgerRows.insertBefore(row, ledgerRows.firstChild);
      while (ledgerRows.children.length > 9)
        ledgerRows.removeChild(ledgerRows.lastChild!);
    }

    // ---- token motion -----------------------------------------------------
    function place(el: HTMLElement, p: P) {
      el.style.transform = "translate(" + p.x + "px," + p.y + "px) translate(-50%,-50%)";
    }
    function jitter(p: P, ry?: number): P {
      return { x: p.x, y: p.y + (Math.random() * 2 - 1) * (ry || 14) };
    }
    const gateTimers = new Map<number, number>();
    function gateFlash(i: number) {
      const g = board!.querySelector('.gate[data-gate="' + i + '"]');
      if (!g) return;
      g.classList.add("active");
      const prev = gateTimers.get(i);
      if (prev) clearTimeout(prev);
      gateTimers.set(
        i,
        after(() => g.classList.remove("active"), 420)
      );
    }

    function runToken(targetGate: number, idx: number) {
      const el = document.createElement("div");
      el.className = "token";
      el.textContent = po(idx);
      tokensEl.appendChild(el);
      const spawn = jitter(G.src[idx % G.src.length], 8);
      place(el, spawn);

      const amber = targetGate === 3;
      let step = 0;
      function next() {
        if (step <= targetGate) {
          place(el, jitter(G.gate[step], 12));
          gateFlash(step);
          step++;
          after(next, 300);
        } else {
          el.classList.add(amber ? "amber" : "green", "pop");
          gc[targetGate]++;
          if (!amber) tally++;
          refreshCounts();
          after(() => {
            place(el, jitter(G.ledger, 10));
            el.style.opacity = "0";
            after(() => {
              el.remove();
              processed++;
              addLedgerRow(po(idx), amber);
              refreshCounts();
              if (amber) discrep.style.display = "";
            }, 320);
          }, 160);
        }
      }
      requestAnimationFrame(() => requestAnimationFrame(next));
    }

    // ---- run cycle --------------------------------------------------------
    let running = false;
    function reset() {
      gc = [0, 0, 0, 0];
      tally = 0;
      processed = 0;
      tokensEl.innerHTML = "";
      ledgerRows.innerHTML = "";
      discrep.style.display = "none";
      refreshCounts();
    }
    function fillFinal() {
      gc = GATE_MAX.slice();
      tally = 29;
      processed = TOTAL;
      refreshCounts();
      for (let i = 0; i < 8; i++) addLedgerRow(po(i), false);
      addLedgerRow("PO-428804", true);
      discrep.style.display = "";
    }
    function run() {
      if (running) return;
      measure();
      drawBeams();
      if (reduce) {
        reset();
        fillFinal();
        return;
      }
      running = true;
      reset();
      buildPlan();
      let i = 0;
      (function spawn() {
        if (i >= PLAN.length) {
          running = false;
          return;
        }
        runToken(PLAN[i], i);
        i++;
        after(spawn, 150 + Math.random() * 70);
      })();
      after(() => {
        running = false;
      }, PLAN.length * 220 + 1400);
    }

    // ---- triggers ---------------------------------------------------------
    runBtn.addEventListener("click", run);

    let started = false;
    function inView(el: Element) {
      const r = el.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      return r.top < vh * 0.7 && r.bottom > vh * 0.2;
    }
    function maybeStart() {
      if (started) return;
      if (inView(board!)) {
        started = true;
        measure();
        drawBeams();
        after(run, 300);
      }
    }
    let et = false;
    const onScroll = () => {
      if (et) return;
      et = true;
      requestAnimationFrame(() => {
        maybeStart();
        et = false;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    let rt = 0;
    const onResize = () => {
      clearTimeout(rt);
      rt = window.setTimeout(() => {
        measure();
        drawBeams();
      }, 160);
    };
    window.addEventListener("resize", onResize);

    // initial geometry pass once layout settles
    after(() => {
      measure();
      drawBeams();
      maybeStart();
    }, 120);

    return () => {
      timers.forEach((id) => clearTimeout(id));
      gateTimers.forEach((id) => clearTimeout(id));
      clearTimeout(rt);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      runBtn.removeEventListener("click", run);
    };
  }, []);

  return (
    <section className="section rule-top" id="engine">
      <div className="wrap">
        <div style={{ maxWidth: 760 }}>
          <Reveal as="span" className="eyebrow">
            <span className="idx">02</span>&nbsp;The engine
          </Reveal>
          <Reveal as="div" delay={1}>
            <h2 className="h-sec" style={{ marginTop: 20 }}>
              Four gates. Every line resolved, or flagged.
            </h2>
          </Reveal>
          <Reveal as="div" delay={2}>
            <p className="lede" style={{ marginTop: 18 }}>
              Messy sources flow in on the left. Each row passes through four
              matching layers — most resolve green at the first gate; a precise
              few reach AI fallback for human review. Watch it run.
            </p>
          </Reveal>
        </div>

        <Reveal className="engine-wrap" delay={2}>
          <div className="engine" ref={boardRef}>
            <svg className="beams" aria-hidden="true" />
            <div className="tokens" aria-hidden="true" />

            {/* LEFT: sources */}
            <div className="engine-col">
              <div className="col-head">
                <span className="t">Sources</span>
                <span className="c">6 feeds</span>
              </div>
              <div className="src">
                {SOURCES.map((s, i) => (
                  <div className="src-item" key={i}>
                    <span className={"si-ic" + (s.erp ? " erp" : "")} />
                    <span className="si-n">{s.n}</span>
                    <span className="si-m">{s.m}</span>
                    <span className="src-anchor" />
                  </div>
                ))}
              </div>
              <button
                className="btn btn-ghost run-btn"
                style={{ marginTop: 20, width: "100%", justifyContent: "center", fontSize: 13, padding: 10 }}
              >
                Re-run match ↻
              </button>
            </div>

            {/* MIDDLE: gates */}
            <div className="engine-col">
              <div className="col-head">
                <span className="t">Matching engine</span>
                <span className="c gate-progress">0 / 0</span>
              </div>
              <div className="gates">
                {GATES.map((g, i) => (
                  <div className={"gate" + (g.ai ? " ai" : "")} data-gate={i} key={i}>
                    <div className="gate-top">
                      <span className="gate-name">
                        <span className="gate-idx">{g.idx}</span>
                        {g.name}
                      </span>
                      <span className="gate-count" data-gc={i}>
                        0
                      </span>
                    </div>
                    <div className="gate-sub">{g.sub}</div>
                    <div className="gate-bar">
                      <i data-gbar={i} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* RIGHT: ledger */}
            <div className="engine-col">
              <div className="col-head">
                <span className="t">Reconciled ledger</span>
                <span className="c">
                  <span
                    className="dot dot-green"
                    style={{ display: "inline-block", marginRight: 5 }}
                  />
                  matched
                </span>
              </div>
              <div className="ledger-head">
                <span className="ledger-tally">
                  <span data-tally>0</span>
                  <span className="of">
                    {" / "}
                    <span data-total>0</span>
                  </span>
                </span>
                <span className="cap" style={{ marginBottom: 4 }}>
                  lines
                </span>
                <span data-ledger style={{ marginLeft: "auto" }} />
              </div>
              <div className="ledger-rows" />
              <div className="discrep" style={{ display: "none" }}>
                <div className="dh">
                  <span className="dot dot-amber" />
                  Discrepancy report
                </div>
                <div className="dt">
                  <b>1 line</b> on Bangkok Polymer statement (
                  <span className="mono">PO 428804 · 180 units</span>) has no
                  matching ERP receipt — <b>flagged for review</b>.
                </div>
              </div>
            </div>
          </div>

          <div className="engine-foot">
            <div className="engine-legend">
              <span className="lg">
                <span className="dot dot-green" />
                Reconciled · ~80% exact
              </span>
              <span className="lg">
                <span className="dot dot-amber" />
                Human review · &lt;2%
              </span>
              <span className="lg" style={{ color: "var(--ink-mute)" }}>
                18,420 lines / monthly cycle
              </span>
            </div>
            <a href="#demo" className="btn btn-green">
              Run it on your data <span className="arrow">→</span>
            </a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
