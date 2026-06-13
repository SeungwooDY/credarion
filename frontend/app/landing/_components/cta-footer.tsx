import { LogoMark, Reveal } from "./primitives";

export function CtaBand() {
  return (
    <section className="cta-band rule-top" id="demo">
      <div className="ledger-bg" aria-hidden="true" />
      <div className="wrap">
        <Reveal as="div">
          <h2 className="display" style={{ fontSize: "clamp(34px,5vw,68px)" }}>
            Close your next period
            <br />
            in a day, not a week.
          </h2>
        </Reveal>
        <Reveal as="div" delay={1}>
          <p className="lede" style={{ margin: "22px auto 32px", textAlign: "center" }}>
            See Credarion reconcile a month of your own supplier statements —
            live, in under twenty minutes.
          </p>
        </Reveal>
        <Reveal
          delay={2}
          style={{ display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}
        >
          <a href="#demo" className="btn btn-ink">
            Book a demo <span className="arrow">→</span>
          </a>
          <a href="#engine" className="btn btn-ghost">
            Watch the engine again
          </a>
        </Reveal>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="foot">
      <div className="wrap">
        <div className="foot-grid">
          <div className="foot-col">
            <a className="brand" href="#top" style={{ marginBottom: 16 }}>
              <LogoMark />
              <span className="word">Credarion</span>
            </a>
            <p className="lede" style={{ fontSize: 14, maxWidth: "34ch" }}>
              The AI accounting co-pilot for Asia-Pacific mid-market finance.
              Reconciliation, resolved.
            </p>
          </div>
          <div className="foot-col">
            <h5>Product</h5>
            <a href="#engine">The engine</a>
            <a href="#mess">Statement ingestion</a>
            <a href="#result">Reconciliation</a>
            <a href="#">Consolidation</a>
            <a href="#">Cash forecasting</a>
          </div>
          <div className="foot-col">
            <h5>Company</h5>
            <a href="#">About</a>
            <a href="#">Security</a>
            <a href="#">Audit &amp; compliance</a>
            <a href="#">Careers</a>
          </div>
          <div className="foot-col">
            <h5>Connect</h5>
            <a href="#demo">Book a demo</a>
            <a href="#">Documentation</a>
            <a href="#">Status</a>
            <a href="#">Contact</a>
          </div>
        </div>
        <div className="foot-bottom">
          <span className="cap">© 2026 Credarion Pte. Ltd. · Singapore</span>
          <span className="cap" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span className="dot dot-green" />
            All systems reconciled
          </span>
        </div>
      </div>
    </footer>
  );
}
