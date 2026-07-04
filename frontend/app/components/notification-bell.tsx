"use client";

import { useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";

export type NotificationTone = "info" | "warning" | "urgent";

export interface BellNotification {
  id: string;
  title: string;
  detail?: string;
  tone?: NotificationTone;
  unread?: boolean;
  /** Optional destination; clicking the notification navigates here. */
  href?: string;
}

const TONE_DOT: Record<NotificationTone, string> = {
  info: "bg-blue-500",
  warning: "bg-amber-500",
  urgent: "bg-red-500",
};

/**
 * Notification bell with an unread-count badge and a click-to-open popover.
 * Purely presentational — the parent passes already-translated notifications
 * and handles clicks (mark read + navigate), so this stays i18n-agnostic.
 */
export default function NotificationBell({
  notifications,
  unreadCount,
  title,
  emptyLabel,
  markAllLabel,
  onItemClick,
  onMarkAllRead,
}: {
  notifications: BellNotification[];
  unreadCount: number;
  title: string;
  emptyLabel: string;
  markAllLabel: string;
  onItemClick: (n: BellNotification) => void;
  onMarkAllRead: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const hasUrgent = notifications.some((n) => n.tone === "urgent" && n.unread);

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
        className="relative inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span
            className={`absolute -right-0.5 -top-0.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none text-white ${
              hasUrgent ? "bg-red-500" : "bg-amber-500"
            }`}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-80 overflow-hidden rounded-xl border border-border bg-card shadow-lg">
          <div className="border-b border-border px-4 py-2.5 text-sm font-semibold text-foreground">
            {title}
          </div>
          {notifications.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-zinc-400">
              {emptyLabel}
            </div>
          ) : (
            <>
              <ul className="max-h-80 overflow-y-auto">
                {notifications.map((n) => (
                  <li key={n.id} className="border-b border-border last:border-b-0">
                    <button
                      type="button"
                      className={`block w-full text-left transition-colors hover:bg-muted ${
                        n.unread ? "" : "opacity-60"
                      }`}
                      onClick={() => {
                        setOpen(false);
                        onItemClick(n);
                      }}
                    >
                      <div className="flex gap-2.5 px-4 py-3">
                        <span
                          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                            n.unread ? TONE_DOT[n.tone ?? "info"] : "bg-zinc-300"
                          }`}
                        />
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-foreground">
                            {n.title}
                          </div>
                          {n.detail && (
                            <div className="mt-0.5 text-xs text-zinc-500">
                              {n.detail}
                            </div>
                          )}
                        </div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={onMarkAllRead}
                  className="block w-full border-t border-border px-4 py-2 text-center text-xs font-medium text-accent transition-colors hover:bg-muted"
                >
                  {markAllLabel}
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
