const SYSTEMS: [string, string][] = [
  ["Kingdee", "金蝶"], ["Yonyou", "用友"], ["SAP", "ERP"], ["Oracle NetSuite", "ERP"],
  ["Xero", "XR"], ["QuickBooks", "QB"], ["MYOB", "AU"], ["Sage", "UK"],
  ["Microsoft Dynamics", "365"], ["HSBC", "BANK"], ["DBS", "BANK"], ["Wise", "FX"],
];

export function Marquee() {
  // duplicate the list for a seamless -50% loop
  const items = SYSTEMS.concat(SYSTEMS);
  return (
    <section className="marquee" aria-label="Supported systems">
      <div className="marquee-track">
        {items.map((s, i) => (
          <span className="mq" key={i} aria-hidden={i >= SYSTEMS.length}>
            <span className="nm">{s[0]}</span>
            <span className="cn">{s[1]}</span>
          </span>
        ))}
      </div>
    </section>
  );
}
