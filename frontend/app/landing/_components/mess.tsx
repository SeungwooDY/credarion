"use client";

import { useEffect, useRef } from "react";
import { Reveal } from "./primitives";

type Stmt = {
  rot: number;
  x: number;
  y: number;
  z: number;
  name: string;
  fmt: string;
  head: { label: string; r?: boolean }[];
  rows: { cells: { v: string; r?: boolean }[]; flag?: boolean }[];
};

const STATEMENTS: Stmt[] = [
  {
    rot: -13, x: 0, y: 40, z: 1,
    name: "Shenzhen Ruiyang Plastics", fmt: "xlsx",
    head: [{ label: "采购订单" }, { label: "物料" }, { label: "数量", r: true }],
    rows: [
      { cells: [{ v: "PO-428759" }, { v: "RY-08831" }, { v: "1,200", r: true }] },
      { cells: [{ v: "PO-428760" }, { v: "RY-08842" }, { v: "640", r: true }] },
      { cells: [{ v: "PO-428771" }, { v: "RY-09001" }, { v: "2,000", r: true }] },
    ],
  },
  {
    rot: -6, x: 36, y: 18, z: 2,
    name: "Acme Components (HK)", fmt: "csv",
    head: [{ label: "Order Ref" }, { label: "Qty", r: true }, { label: "Unit £", r: true }],
    rows: [
      { cells: [{ v: "428759.0" }, { v: "1200", r: true }, { v: "3.4200", r: true }] },
      { cells: [{ v: "428762.0" }, { v: "300", r: true }, { v: "9.1000", r: true }] },
      { cells: [{ v: "428765.0" }, { v: "75", r: true }, { v: "21.500", r: true }] },
    ],
  },
  {
    rot: 1, x: 74, y: 2, z: 3,
    name: "Tan Seng Metals Pte", fmt: "pdf",
    head: [{ label: "P/O #" }, { label: "Part" }, { label: "Amount", r: true }],
    rows: [
      { cells: [{ v: "PO428759" }, { v: "TS/441" }, { v: "4,104.00", r: true }] },
      { cells: [{ v: "PO428780" }, { v: "TS/562" }, { v: "1,890.00", r: true }] },
      { cells: [{ v: "PO428781" }, { v: "TS/563" }, { v: "512.40", r: true }] },
    ],
  },
  {
    rot: 8, x: 112, y: 20, z: 4,
    name: "Yongtai Industrial 永泰", fmt: "xls",
    head: [{ label: "Purchase Order" }, { label: "Recd", r: true }],
    rows: [
      { cells: [{ v: "4 28759" }, { v: "1.20k", r: true }] },
      { cells: [{ v: "4 28790" }, { v: "0.95k", r: true }] },
      { cells: [{ v: "— blank —" }, { v: "0.40k", r: true }], flag: true },
    ],
  },
  {
    rot: 15, x: 150, y: 46, z: 5,
    name: "Bangkok Polymer Co.", fmt: "scan",
    head: [{ label: "เลขที่ PO" }, { label: "จำนวน", r: true }],
    rows: [
      { cells: [{ v: "PO 428759" }, { v: "1,200", r: true }] },
      { cells: [{ v: "PO 428803" }, { v: "3,300", r: true }] },
      { cells: [{ v: "PO 428804" }, { v: "180", r: true }] },
    ],
  },
];

export function Mess() {
  const fanRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const fan = fanRef.current;
    if (!fan) return;
    const cards = Array.from(fan.querySelectorAll<HTMLElement>(".stmt"));

    function layout() {
      if (!fan) return;
      const narrow = fan.clientWidth < 420;
      cards.forEach((c) => {
        let rot = parseFloat(c.dataset.rot || "0");
        let x = parseFloat(c.dataset.x || "0");
        const y = parseFloat(c.dataset.y || "0");
        const z = parseInt(c.dataset.z || "0", 10);
        if (narrow) {
          rot *= 0.55;
          x *= 0.5;
        }
        c.style.left = `${x}px`;
        c.style.bottom = `${y}px`;
        c.style.zIndex = `${z}`;
        c.style.transform = `rotate(${rot}deg)`;
      });
    }

    const enter: ((this: HTMLElement) => void)[] = [];
    const leave: ((this: HTMLElement) => void)[] = [];
    cards.forEach((c, i) => {
      const onEnter = function (this: HTMLElement) {
        this.style.transform = "rotate(0deg) translateY(-8px)";
        this.style.zIndex = "20";
      };
      const onLeave = function (this: HTMLElement) {
        let rot = parseFloat(this.dataset.rot || "0");
        if (fan && fan.clientWidth < 420) rot *= 0.55;
        this.style.transform = `rotate(${rot}deg)`;
        this.style.zIndex = this.dataset.z || "1";
      };
      enter[i] = onEnter;
      leave[i] = onLeave;
      c.addEventListener("mouseenter", onEnter);
      c.addEventListener("mouseleave", onLeave);
    });

    layout();
    window.addEventListener("resize", layout);
    return () => {
      window.removeEventListener("resize", layout);
      cards.forEach((c, i) => {
        c.removeEventListener("mouseenter", enter[i]);
        c.removeEventListener("mouseleave", leave[i]);
      });
    };
  }, []);

  return (
    <section className="section rule-top" id="mess">
      <div className="wrap">
        <div style={{ maxWidth: 760 }}>
          <Reveal as="span" className="eyebrow">
            <span className="idx">01</span>&nbsp;The mess
          </Reveal>
          <Reveal as="div" delay={1}>
            <h2 className="h-sec" style={{ marginTop: 20 }}>
              Five suppliers. Five formats. One version of the truth that
              doesn&apos;t exist yet.
            </h2>
          </Reveal>
          <Reveal as="div" delay={2}>
            <p className="lede" style={{ marginTop: 18 }}>
              Every statement arrives in its own shape — different headers,
              different column names for the same field, a PO stored as a float
              in one system and a string in another. This is the complexity
              Credarion eats for breakfast.
            </p>
          </Reveal>
        </div>

        <div className="mess-grid">
          <Reveal className="fan" delay={2}>
            <div ref={fanRef} style={{ position: "absolute", inset: 0 }}>
              {STATEMENTS.map((s, i) => (
                <div
                  key={i}
                  className="stmt"
                  data-rot={s.rot}
                  data-x={s.x}
                  data-y={s.y}
                  data-z={s.z}
                >
                  <div className="stmt-h">
                    <span className="nm">{s.name}</span>
                    <span className="fmt">{s.fmt}</span>
                  </div>
                  <table>
                    <thead>
                      <tr>
                        {s.head.map((h, j) => (
                          <th key={j} className={h.r ? "r" : undefined}>
                            {h.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {s.rows.map((row, j) => (
                        <tr key={j} className={row.flag ? "flag-cell" : undefined}>
                          {row.cells.map((c, k) => (
                            <td key={k} className={c.r ? "r" : undefined}>
                              {c.v}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          </Reveal>

          <Reveal className="friction-list" delay={3}>
            <div className="friction">
              <span className="fi">·01</span>
              <div>
                <div className="ft">The same PO, five ways</div>
                <div className="fd">
                  <code>428759.0</code>
                  <span className="x">vs</span>
                  <code>PO428759</code>
                  <span className="x">vs</span>
                  <code>4 28759</code>
                </div>
              </div>
            </div>
            <div className="friction">
              <span className="fi">·02</span>
              <div>
                <div className="ft">Trailing-float corruption</div>
                <div className="fd">
                  Excel silently turns a reference into a number —{" "}
                  <code>428759.0</code> will never equal <code>428759</code>.
                </div>
              </div>
            </div>
            <div className="friction">
              <span className="fi">·03</span>
              <div>
                <div className="ft">Headers in three languages</div>
                <div className="fd">
                  <code>采购订单</code>
                  <span className="x">·</span>
                  <code>Order Ref</code>
                  <span className="x">·</span>
                  <code>เลขที่ PO</code> — all the same field.
                </div>
              </div>
            </div>
            <div className="friction">
              <span className="fi">·04</span>
              <div>
                <div className="ft">Currency &amp; unit drift</div>
                <div className="fd">
                  <code>¥</code>
                  <span className="x">·</span>
                  <code>£</code>
                  <span className="x">·</span>
                  <code>RMB</code>, quantities in <code>1.20k</code> vs{" "}
                  <code>1,200</code>.
                </div>
              </div>
            </div>
            <div className="friction">
              <span className="fi">·05</span>
              <div>
                <div className="ft">Missing &amp; merged cells</div>
                <div className="fd">
                  Blank PO numbers, merged headers, scanned PDFs — the rows Excel
                  quietly drops.
                </div>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
