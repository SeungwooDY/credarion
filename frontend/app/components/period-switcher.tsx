"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, Check, ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { useLang, useT } from "@/app/lib/i18n";
import { currentPeriod, shiftPeriod, usePeriod } from "@/app/lib/period";
import { useCurrentOrg, usePeriods, useSignoff } from "@/app/lib/swr";

/** Localized "Mar 2026" / "2026年3月" label for a "YYYY-MM" period. */
export function usePeriodLabel(period: string): string {
  const { lang } = useLang();
  return useMemo(() => {
    if (!/^\d{4}-\d{2}$/.test(period)) return "";
    const [y, m] = period.split("-").map(Number);
    return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
      month: "short",
      year: "numeric",
    }).format(new Date(y, m - 1, 1));
  }, [period, lang]);
}

/**
 * Read-only chip showing the globally selected month (+ lock state) — rendered
 * on each page so users always know which period they're looking at. The
 * sidebar switcher is the single control.
 */
export function PeriodBadge() {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const { period } = usePeriod();
  const { locked } = useSignoff(orgId, period);
  const label = usePeriodLabel(period);
  if (!period) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
        locked
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-border bg-muted text-zinc-600"
      }`}
      title={locked ? t("period.locked") : undefined}
    >
      <CalendarDays className="h-3.5 w-3.5" />
      {label}
      {locked && <Lock className="h-3 w-3" />}
    </span>
  );
}

/**
 * Sidebar month switcher — the app's single period control.
 *
 * Collapsed rail: calendar icon with the month number as a badge.
 * Expanded: ‹ label › steppers; the label opens a dropdown of the org's
 * periods (derived from data; locked months show a lock icon).
 */
export default function PeriodSwitcher({ isCollapsed }: { isCollapsed: boolean }) {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const { period, setPeriod } = usePeriod();
  const { periods } = usePeriods(orgId);
  const label = usePeriodLabel(period);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Default once periods load: latest month with data, else current month.
  useEffect(() => {
    if (period || periods.length === 0) return;
    const latestWithData = periods.find((p) => p.has_data)?.period;
    setPeriod(latestWithData ?? currentPeriod());
  }, [period, periods, setPeriod]);

  // Close the dropdown on outside click / Escape.
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

  const monthNum = period ? period.slice(5) : "--";
  const selectedLocked = periods.find((p) => p.period === period)?.locked ?? false;

  return (
    <div
      ref={ref}
      className="relative w-full border-b border-border px-2 py-1.5"
      aria-label={t("period.switcher_aria")}
    >
      {isCollapsed ? (
        <div
          className="relative mx-auto flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground"
          title={label}
        >
          <CalendarDays className="h-4 w-4" />
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-accent px-0.5 text-[9px] font-semibold leading-none text-white">
            {monthNum}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => period && setPeriod(shiftPeriod(period, -1))}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent"
            aria-label={t("period.prev_month")}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex h-7 flex-1 items-center justify-center gap-1.5 rounded-md text-sm font-medium text-foreground transition hover:bg-muted"
          >
            <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
            {label || t("common.loading")}
            {selectedLocked && <Lock className="h-3 w-3 text-emerald-600" />}
          </button>
          <button
            type="button"
            onClick={() => period && setPeriod(shiftPeriod(period, 1))}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent"
            aria-label={t("period.next_month")}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {open && !isCollapsed && (
        <div className="absolute left-2 right-2 top-full z-50 mt-1 max-h-72 overflow-y-auto rounded-xl border border-border bg-card shadow-lg">
          <div className="border-b border-border px-3 py-2 text-xs font-semibold text-zinc-500">
            {t("period.jump_to")}
          </div>
          {periods.length === 0 ? (
            <div className="px-3 py-3 text-center text-xs text-zinc-400">
              {t("common.loading")}
            </div>
          ) : (
            <ul>
              {periods.map((p) => (
                <li key={p.period}>
                  <button
                    type="button"
                    onClick={() => {
                      setPeriod(p.period);
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-muted ${
                      p.period === period ? "font-semibold text-accent" : "text-foreground"
                    } ${p.has_data ? "" : "opacity-50"}`}
                  >
                    <PeriodOptionLabel period={p.period} />
                    {!p.has_data && (
                      <span className="text-[10px] text-zinc-400">
                        {t("period.no_data")}
                      </span>
                    )}
                    <span className="ml-auto flex items-center gap-1.5">
                      {p.locked && <Lock className="h-3 w-3 text-emerald-600" />}
                      {p.period === period && <Check className="h-3.5 w-3.5" />}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function PeriodOptionLabel({ period }: { period: string }) {
  return <span>{usePeriodLabel(period)}</span>;
}
