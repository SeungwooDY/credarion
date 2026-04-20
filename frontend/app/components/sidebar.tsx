"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/ingestion", label: "Data Ingestion" },
  { href: "/reconciliation", label: "Reconciliation" },
  { href: "/invoices", label: "Invoices" },
  { href: "/settings", label: "Settings" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-56 shrink-0 border-r border-[var(--border)] bg-[var(--muted)] flex flex-col">
      <div className="px-5 py-5 border-b border-[var(--border)]">
        <h1 className="text-lg font-semibold tracking-tight">Credarion</h1>
        <p className="text-xs text-zinc-500 mt-0.5">Accounting Co-pilot</p>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ href, label }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`block px-3 py-2 rounded text-sm transition-colors ${
                active
                  ? "bg-[var(--accent)] text-white font-medium"
                  : "text-zinc-600 hover:bg-zinc-200"
              }`}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="px-5 py-4 border-t border-[var(--border)] text-xs text-zinc-400">
        v0.1.0 &middot; Phase 3
      </div>
    </aside>
  );
}
