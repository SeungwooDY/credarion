"use client";

/**
 * Global accounting-period store for Credarion.
 *
 * The sidebar's period switcher is the single control; every page reads the
 * selected period from here so switching months re-scopes all data at once.
 * Persisted to localStorage (mirrors close-date.ts / i18n.tsx): client-only,
 * SSR snapshot is "" so nothing period-dependent renders during SSR (pages
 * treat "" as "not chosen yet" and skip fetches — SWR keys are already null
 * on empty period).
 */
import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "credarion-period";
const PERIOD_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

const listeners = new Set<() => void>();

/** The current calendar month as a "YYYY-MM" period string. */
export function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** Step a period by ±n months: shiftPeriod("2026-01", -1) → "2025-12". */
export function shiftPeriod(period: string, by: number): string {
  if (!PERIOD_RE.test(period)) return period;
  const [y, m] = period.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** Days from today until the last day of the current month (0 on the last day). */
export function daysUntilMonthEnd(): number {
  const now = new Date();
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return lastDay - now.getDate();
}

/**
 * Months the user may explicitly create today, oldest first: the current
 * month anytime, the next month only within the last 5 days of the current
 * one. Mirrors backend can_create_period (app/periods.py) — the server
 * enforces the window; this only decides what to offer in the UI.
 */
export function creatablePeriods(): string[] {
  const cur = currentPeriod();
  const out = [cur];
  if (daysUntilMonthEnd() <= 5) out.push(shiftPeriod(cur, 1));
  return out;
}

/** Stored period, or "" when unset/invalid ("not chosen yet"). */
function read(): string {
  const v = window.localStorage.getItem(STORAGE_KEY) ?? "";
  return PERIOD_RE.test(v) ? v : "";
}

function write(period: string) {
  if (!PERIOD_RE.test(period)) return;
  window.localStorage.setItem(STORAGE_KEY, period);
  listeners.forEach((fn) => fn());
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

export function usePeriod(): { period: string; setPeriod: (p: string) => void } {
  const period = useSyncExternalStore(subscribe, read, () => "");
  const setPeriod = useCallback((p: string) => write(p), []);
  return { period, setPeriod };
}
