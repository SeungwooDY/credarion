"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "../lib/swr";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "home" },
  { href: "/ingestion", label: "Data Ingestion", icon: "upload" },
  { href: "/reconciliation", label: "Reconciliation", icon: "check" },
  { href: "/mismatches", label: "Mismatches", icon: "alert" },
  { href: "/invoices", label: "Invoices", icon: "file" },
  { href: "/settings", label: "Settings", icon: "gear" },
];

const ICONS: Record<string, React.ReactNode> = {
  home: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z" />
      <path d="M9 21V12h6v9" />
    </svg>
  ),
  upload: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  ),
  check: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
  alert: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  file: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  ),
  gear: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  ),
};

const PLAN_LABELS: Record<string, string> = {
  starter: "Starter",
  growth: "Growth",
  enterprise: "Enterprise",
};

export default function Sidebar() {
  const pathname = usePathname();
  const { me } = useMe();

  async function handleLogout() {
    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      window.location.assign("/login");
    }
  }

  const displayName = me?.full_name || me?.email || "";
  const initial = (displayName || "?").charAt(0).toUpperCase();

  return (
    <aside className="w-56 shrink-0 bg-background flex flex-col">
      <div className="px-5 pt-6 pb-5">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark">
            C
          </div>
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight text-foreground">
              Credarion
            </h1>
            <p className="text-[10px] text-zinc-400 tracking-wide uppercase leading-none">
              Accounting Co-pilot
            </p>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-2 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 ${
                active
                  ? "text-accent font-medium bg-accent-light"
                  : "text-zinc-500 hover:text-zinc-800 hover:bg-muted"
              }`}
            >
              <span className={active ? "text-accent" : "text-zinc-400"}>
                {ICONS[icon]}
              </span>
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto px-3 pb-4 pt-2">
        {me && (
          <div className="rounded-xl bg-muted px-3 py-2.5">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark text-[11px] font-bold text-white">
                {initial}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium text-zinc-800">
                  {displayName}
                </div>
                <div className="truncate text-[11px] text-zinc-400">
                  {me.account.name}
                  {PLAN_LABELS[me.account.plan]
                    ? ` · ${PLAN_LABELS[me.account.plan]}`
                    : ""}
                </div>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-[12px] font-medium text-zinc-500 transition hover:bg-white hover:text-zinc-800"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              Sign out
            </button>
          </div>
        )}
        <div className="px-2 pt-3 text-[11px] tracking-wide text-zinc-300">
          v0.1.0
        </div>
      </div>
    </aside>
  );
}
