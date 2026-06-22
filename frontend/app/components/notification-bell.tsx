"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell } from "lucide-react";

export type NotificationTone = "info" | "warning" | "urgent";

export interface DashboardNotification {
  id: string;
  title: string;
  detail?: string;
  tone?: NotificationTone;
  /** Optional destination; clicking the notification navigates here. */
  href?: string;
}

const TONE_DOT: Record<NotificationTone, string> = {
  info: "bg-blue-500",
  warning: "bg-amber-500",
  urgent: "bg-red-500",
};

/**
 * Header notification bell with a count badge and a click-to-open popover.
 * Purely presentational — the parent passes already-translated notifications,
 * so this component stays i18n-agnostic and reusable across pages.
 */
export default function NotificationBell({
  notifications,
  title,
  emptyLabel,
}: {
  notifications: DashboardNotification[];
  title: string;
  emptyLabel: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const count = notifications.length;
  const hasUrgent = notifications.some((n) => n.tone === "urgent");

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={title}
        aria-expanded={open}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-card text-zinc-500 transition-colors hover:bg-muted hover:text-zinc-700"
      >
        <Bell className="h-[18px] w-[18px]" />
        {count > 0 && (
          <span
            className={`absolute -right-1 -top-1 flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none text-white ${
              hasUrgent ? "bg-red-500" : "bg-amber-500"
            }`}
          >
            {count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-xl border border-border bg-card shadow-lg">
          <div className="border-b border-border px-4 py-2.5 text-sm font-semibold text-foreground">
            {title}
          </div>
          {count === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-zinc-400">{emptyLabel}</div>
          ) : (
            <ul className="max-h-80 overflow-y-auto">
              {notifications.map((n) => {
                const body = (
                  <div className="flex gap-2.5 px-4 py-3">
                    <span
                      className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${TONE_DOT[n.tone ?? "info"]}`}
                    />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-foreground">{n.title}</div>
                      {n.detail && (
                        <div className="mt-0.5 text-xs text-zinc-500">{n.detail}</div>
                      )}
                    </div>
                  </div>
                );
                return (
                  <li key={n.id} className="border-b border-border last:border-b-0">
                    {n.href ? (
                      <Link
                        href={n.href}
                        className="block no-underline transition-colors hover:bg-muted"
                        onClick={() => setOpen(false)}
                      >
                        {body}
                      </Link>
                    ) : (
                      body
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
