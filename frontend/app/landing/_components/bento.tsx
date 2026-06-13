import { Reveal } from "./primitives";

type Cell = { w: "w3" | "w2"; slug: string; title: string; copy: string; mini?: string };

const CELLS: Cell[] = [
  {
    w: "w3", slug: "/ bank-reconciliation", title: "Bank reconciliation",
    copy: "Match bank lines to invoices and receipts across every entity account, in every currency.",
    mini: "99.1% auto-cleared",
  },
  {
    w: "w3", slug: "/ consolidation", title: "Multi-entity consolidation",
    copy: "Roll up subsidiaries across HK, SG, CN and TH — intercompany eliminations reconciled automatically.",
    mini: "14 entities · 1 ledger",
  },
  {
    w: "w2", slug: "/ forecast", title: "Cash forecasting",
    copy: "Forward your reconciled position into a 13-week cash view.",
  },
  {
    w: "w2", slug: "/ ingestion", title: "Statement ingestion",
    copy: "xlsx, csv, pdf, scans — any layout, any language, normalized on upload.",
    mini: "5+ formats",
  },
  {
    w: "w2", slug: "/ audit", title: "Audit-ready trail",
    copy: "Every match, override and resolution note logged and exportable for your auditors.",
  },
];

export function Bento() {
  return (
    <section className="section rule-top">
      <div className="wrap">
        <div style={{ maxWidth: 760 }}>
          <Reveal as="span" className="eyebrow">
            Beyond reconciliation
          </Reveal>
          <Reveal as="div" delay={1}>
            <h2 className="h-sec" style={{ marginTop: 20 }}>
              One co-pilot for the whole close.
            </h2>
          </Reveal>
        </div>
        <Reveal className="bento" delay={1}>
          {CELLS.map((c) => (
            <div className={"cell " + c.w} key={c.slug}>
              <span className="ci">{c.slug}</span>
              <h4>{c.title}</h4>
              <p>{c.copy}</p>
              {c.mini && <span className="mini">{c.mini}</span>}
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
