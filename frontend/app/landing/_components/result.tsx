import { Reveal, Ticker } from "./primitives";

const PANEL_STYLE = { marginTop: 44 } as const;

type Row = {
  po: string;
  part: string;
  layer: string;
  erp: string;
  stmt: string;
  amount: string;
  status: "matched" | "flagged";
};

const ROWS: Row[] = [
  { po: "PO-428759", part: "RY-08831", layer: "Exact", erp: "1,200", stmt: "1,200", amount: "4,104.00", status: "matched" },
  { po: "PO-428760", part: "RY-08842", layer: "Exact", erp: "640", stmt: "640", amount: "5,824.00", status: "matched" },
  { po: "PO-428762", part: "AC-1190", layer: "Fuzzy", erp: "300", stmt: "300", amount: "2,730.00", status: "matched" },
  { po: "PO-428780", part: "TS-562", layer: "Multi-PO", erp: "1,890", stmt: "1,890", amount: "1,890.00", status: "matched" },
  { po: "PO-428804", part: "BP-007", layer: "AI", erp: "—", stmt: "180", amount: "3,240.00", status: "flagged" },
];

export function Result() {
  return (
    <section className="section rule-top" id="result">
      <div className="wrap">
        <div style={{ maxWidth: 760 }}>
          <Reveal as="span" className="eyebrow">
            <span className="idx">03</span>&nbsp;The result
          </Reveal>
          <Reveal as="div" delay={1}>
            <h2 className="h-sec" style={{ marginTop: 20 }}>
              Books that close in a day — and an audit trail that proves it.
            </h2>
          </Reveal>
        </div>

        <Reveal className="stat-row" delay={1}>
          <div className="stat">
            <div className="k">Auto-match rate</div>
            <div className="v green">
              <Ticker to={97.3} dec={1} />%
            </div>
            <div className="s">across 240 active suppliers</div>
          </div>
          <div className="stat">
            <div className="k">Close time</div>
            <div className="v">
              7.0<span style={{ color: "var(--ink-faint)" }}>→</span>
              <span className="green">1.5</span>
              <small style={{ fontSize: "0.4em", color: "var(--ink-mute)" }}>d</small>
            </div>
            <div className="s">per monthly reconciliation</div>
          </div>
          <div className="stat">
            <div className="k">Lines reconciled</div>
            <div className="v">
              <Ticker to={18420} dec={0} />
            </div>
            <div className="s">every monthly cycle</div>
          </div>
          <div className="stat">
            <div className="k">Flagged for review</div>
            <div className="v" style={{ color: "var(--review)" }}>
              <Ticker to={1.1} dec={1} />%
            </div>
            <div className="s">true exceptions, not noise</div>
          </div>
        </Reveal>

        <Reveal className="panel-ledger" delay={2} style={PANEL_STYLE}>
          <table className="recon-table">
            <thead>
              <tr>
                <th>PO Number</th>
                <th>Part</th>
                <th>Layer</th>
                <th className="r">ERP Qty</th>
                <th className="r">Stmt Qty</th>
                <th className="r">Amount ¥</th>
                <th className="r">Status</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={row.po} className={row.status}>
                  <td className="po-cell">{row.po}</td>
                  <td>{row.part}</td>
                  <td>{row.layer}</td>
                  <td className="r" style={row.erp === "—" ? { color: "var(--ink-faint)" } : undefined}>
                    {row.erp}
                  </td>
                  <td className="r">{row.stmt}</td>
                  <td className="r">{row.amount}</td>
                  <td className="r">
                    {row.status === "matched" ? (
                      <span className="tag-matched pill">Matched</span>
                    ) : (
                      <span className="tag-review pill">Not in ERP</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
      </div>
    </section>
  );
}
