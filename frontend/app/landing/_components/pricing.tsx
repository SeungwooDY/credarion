import { Reveal } from "./primitives";

type Tier = {
  name: string;
  price: string;
  unit?: string;
  blurb: string;
  features: string[];
  cta: { label: string; variant: "btn-ghost" | "btn-green" };
  feature?: boolean;
};

const TIERS: Tier[] = [
  {
    name: "Close", price: "490", unit: " / entity · mo",
    blurb: "For a single team closing one set of books each month.",
    features: [
      "Supplier reconciliation · 4-layer engine",
      "Up to 50 suppliers",
      "Statement ingestion, all formats",
      "Audit trail & CSV export",
    ],
    cta: { label: "Start a trial", variant: "btn-ghost" },
  },
  {
    name: "Consolidate", price: "1,290", unit: " / entity · mo", feature: true,
    blurb: "For finance teams running multiple entities across the region.",
    features: [
      "Everything in Close",
      "Unlimited suppliers",
      "Multi-entity consolidation",
      "Bank reconciliation & cash forecast",
      "SSO & role-based approvals",
    ],
    cta: { label: "Book a demo", variant: "btn-green" },
  },
  {
    name: "Enterprise", price: "Custom",
    blurb: "For groups with bespoke ERP estates and audit requirements.",
    features: [
      "Everything in Consolidate",
      "Dedicated ERP connectors",
      "On-prem / VPC deployment",
      "SLA & named support",
    ],
    cta: { label: "Talk to us", variant: "btn-ghost" },
  },
];

export function Pricing() {
  return (
    <section className="section rule-top" id="pricing">
      <div className="wrap">
        <div style={{ maxWidth: 760 }}>
          <Reveal as="span" className="eyebrow">
            Pricing
          </Reveal>
          <Reveal as="div" delay={1}>
            <h2 className="h-sec" style={{ marginTop: 20 }}>
              Priced per entity. Calm and predictable.
            </h2>
          </Reveal>
        </div>
        <Reveal className="pricing" delay={1}>
          {TIERS.map((t) => (
            <div className={"tier" + (t.feature ? " feature" : "")} key={t.name}>
              <span className="tn">{t.name}</span>
              <div className="tp">
                {t.unit ? "$" : null}
                <span className="mono">{t.price}</span>
                {t.unit && <small>{t.unit}</small>}
              </div>
              <p className="td">{t.blurb}</p>
              <ul>
                {t.features.map((f) => (
                  <li key={f}>
                    <span className="tk">✓</span>
                    {f}
                  </li>
                ))}
              </ul>
              <a href="#demo" className={"btn " + t.cta.variant}>
                {t.cta.label}
              </a>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
