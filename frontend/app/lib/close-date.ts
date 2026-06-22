"use client";

/**
 * Month-end close date store for Credarion.
 *
 * Each company closes its books on a different day, so the close date is
 * user-configurable (via the calendar dropdown on the dashboard) and persisted
 * to localStorage. Defaults to the last day of the current month.
 *
 * Like the rest of the date-derived UI, this is client-only: the server
 * snapshot is `null` (renders a skeleton) so the countdown is never computed
 * during SSR, avoiding hydration drift around midnight / across timezones.
 */
import { useCallback, useMemo, useSyncExternalStore } from "react";
import {
  type DateValue,
  endOfMonth,
  getLocalTimeZone,
  parseDate,
  today,
} from "@internationalized/date";

const STORAGE_KEY = "credarion-close-date";

const listeners = new Set<() => void>();

/** Stored ISO date ("YYYY-MM-DD"), falling back to this month's last day. */
function read(): string {
  return (
    window.localStorage.getItem(STORAGE_KEY) ??
    endOfMonth(today(getLocalTimeZone())).toString()
  );
}

function write(iso: string) {
  window.localStorage.setItem(STORAGE_KEY, iso);
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

export interface CloseDate {
  /** Selected close date (client) or null during SSR. */
  closeDate: DateValue | null;
  /** Whole days from today until the close date, clamped at 0. Null during SSR. */
  daysLeft: number | null;
  /** Persist a newly chosen close date. */
  setCloseDate: (date: DateValue) => void;
}

export function useCloseDate(): CloseDate {
  const iso = useSyncExternalStore(subscribe, read, () => null as string | null);

  const closeDate = useMemo(() => (iso ? parseDate(iso) : null), [iso]);

  const daysLeft = useMemo(() => {
    if (!closeDate) return null;
    const tz = getLocalTimeZone();
    const ms =
      closeDate.toDate(tz).getTime() - today(tz).toDate(tz).getTime();
    return Math.max(0, Math.round(ms / 86_400_000));
  }, [closeDate]);

  const setCloseDate = useCallback((date: DateValue) => write(date.toString()), []);

  return { closeDate, daysLeft, setCloseDate };
}
