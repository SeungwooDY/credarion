"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, Lock } from "lucide-react";
import { useLang, useT } from "@/app/lib/i18n";
import { usePeriod } from "@/app/lib/period";
import { useCurrentOrg, usePeriods, useSignoff } from "@/app/lib/swr";
import MonthPicker from "./month-picker";

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
 * Expanded: ‹ label › steppers clamped to months that exist; the label opens
 * a month calendar (any past month through December of next year). Months
 * the org already knows show a data dot / lock icon; picking a month that
 * doesn't exist yet creates it first (an "open" sign-off row) so it sticks
 * in the derived period list.
 */
export default function PeriodSwitcher({ isCollapsed }: { isCollapsed: boolean }) {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const { period, setPeriod } = usePeriod();
  const { periods, refreshPeriods } = usePeriods(orgId);
  const label = usePeriodLabel(period);
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  async function createPeriod(p: string) {
    if (!orgId || creating) return;
    setCreating(true);
    setCreateError(false);
    try {
      const res = await fetch("/api/v1/periods", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ org_id: orgId, period: p }),
      });
      // 409 = the month already exists (e.g. created concurrently) — that's
      // still a month we can select.
      if (!res.ok && res.status !== 409) {
        throw new Error(`create period failed: ${res.status}`);
      }
      await refreshPeriods();
      setPeriod(p);
      setOpen(false);
    } catch {
      setCreateError(true);
    } finally {
      setCreating(false);
    }
  }

  // Calendar pick: an existing month just gets selected; an unknown month is
  // created first so the derived period list keeps it.
  function selectMonth(p: string) {
    if (periods.some((row) => row.period === p)) {
      setPeriod(p);
      setOpen(false);
      return;
    }
    void createPeriod(p);
  }

  // Lock flags change when admins sign off / reopen — refetch on open so the
  // dropdown never shows stale locks.
  useEffect(() => {
    if (open) refreshPeriods();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Default once periods load: latest month with data, else newest existing.
  // Also snaps a stale stored selection (a month that no longer exists) back
  // to a real month — months are no longer auto-created, so the stored period
  // is not guaranteed to be in the list.
  useEffect(() => {
    if (periods.length === 0) return;
    if (period && periods.some((p) => p.period === period)) return;
    const latestWithData = periods.find((p) => p.has_data)?.period;
    setPeriod(latestWithData ?? periods[0].period);
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

  // Steppers move within existing months only (list is newest first).
  const idx = periods.findIndex((p) => p.period === period);
  const olderPeriod = idx >= 0 ? periods[idx + 1]?.period : undefined;
  const newerPeriod = idx > 0 ? periods[idx - 1]?.period : undefined;

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
            onClick={() => olderPeriod && setPeriod(olderPeriod)}
            disabled={!olderPeriod}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent disabled:pointer-events-none disabled:opacity-30"
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
            onClick={() => newerPeriod && setPeriod(newerPeriod)}
            disabled={!newerPeriod}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-muted hover:text-accent disabled:pointer-events-none disabled:opacity-30"
            aria-label={t("period.next_month")}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {open && !isCollapsed && (
        <div className="absolute left-2 right-2 top-full z-50 mt-1 rounded-xl border border-border bg-card shadow-lg">
          <div className="border-b border-border px-3 py-2 text-xs font-semibold text-zinc-500">
            {t("period.jump_to")}
          </div>
          <MonthPicker
            value={period}
            periods={periods}
            disabled={creating}
            onSelect={selectMonth}
          />
          {creating && (
            <div className="px-3 pb-2 text-xs text-zinc-400">
              {t("period.creating")}
            </div>
          )}
          {createError && (
            <div className="px-3 pb-2 text-xs text-red-500">
              {t("period.create_failed")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
