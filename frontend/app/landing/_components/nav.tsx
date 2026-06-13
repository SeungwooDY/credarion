import { LogoMark } from "./primitives";

export function Nav() {
  return (
    <header className="nav">
      <div className="wrap nav-inner">
        <a className="brand" href="#top" aria-label="Credarion home">
          <LogoMark />
          <span className="word">Credarion</span>
        </a>
        <nav className="nav-links">
          <a href="#mess">The problem</a>
          <a href="#engine">The engine</a>
          <a href="#result">Results</a>
          <a href="#pricing">Pricing</a>
        </nav>
        <div className="nav-right">
          <span className="nav-status">
            <span className="dot dot-green" />
            97.3% reconciled
          </span>
          <a href="#demo" className="btn btn-ink">
            Book a demo
          </a>
        </div>
      </div>
    </header>
  );
}
