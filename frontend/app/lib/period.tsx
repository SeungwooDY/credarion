"use client";

/**
 * Global org + accounting-period selection for Credarion.
 *
 * Every period-scoped page (reconciliation, mismatches, ingestion, dashboard)
 * reads the active org + month from here instead of keeping its own local state,
 * so the month-tab switcher in the app shell drives the whole product.
 *
 * Mirrors the i18n / close-date pattern: localStorage-backed and hydration-safe
 * via useSyncExternalStore (server snapshot is empty, so nothing is read from
 * storage during SSR). The smart defaulting (first org, newest month) lives in
 * the PeriodBar, which has the fetched org/period lists; this store only holds
 * the current selection.
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
} from "react";

const ORG_KEY = "credarion-org";
const PERIOD_KEY = "credarion-period";

const listeners = new Set<() => void>();

function emit() {
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

// getSnapshot must return a referentially stable value when nothing changed,
// or useSyncExternalStore loops forever — so we memoize the last object.
let cache: { orgId: string; period: string } = { orgId: "", period: "" };

function readSnapshot() {
  const orgId = window.localStorage.getItem(ORG_KEY) ?? "";
  const period = window.localStorage.getItem(PERIOD_KEY) ?? "";
  if (orgId !== cache.orgId || period !== cache.period) {
    cache = { orgId, period };
  }
  return cache;
}

const SERVER_SNAPSHOT = { orgId: "", period: "" };
function readServerSnapshot() {
  return SERVER_SNAPSHOT;
}

interface OrgPeriodValue {
  orgId: string;
  period: string;
  setOrgId: (orgId: string) => void;
  setPeriod: (period: string) => void;
}

const OrgPeriodContext = createContext<OrgPeriodValue | null>(null);

export function OrgPeriodProvider({ children }: { children: React.ReactNode }) {
  const snap = useSyncExternalStore(subscribe, readSnapshot, readServerSnapshot);

  const setOrgId = useCallback((orgId: string) => {
    window.localStorage.setItem(ORG_KEY, orgId);
    emit();
  }, []);

  const setPeriod = useCallback((period: string) => {
    window.localStorage.setItem(PERIOD_KEY, period);
    emit();
  }, []);

  const value = useMemo(
    () => ({ orgId: snap.orgId, period: snap.period, setOrgId, setPeriod }),
    [snap, setOrgId, setPeriod]
  );

  return <OrgPeriodContext.Provider value={value}>{children}</OrgPeriodContext.Provider>;
}

export function useOrgPeriod(): OrgPeriodValue {
  const ctx = useContext(OrgPeriodContext);
  if (!ctx) throw new Error("useOrgPeriod must be used within an OrgPeriodProvider");
  return ctx;
}
