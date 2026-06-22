/**
 * SWR fetcher and shared hooks for Credarion.
 * Data is cached client-side and revalidated in the background,
 * so page navigations are instant after the first load.
 */
import useSWR, { type SWRConfiguration } from "swr";

const API_BASE = "/api/v1";

/** Default fetcher: prepends API_BASE, throws on non-ok responses. */
export async function fetcher<T = unknown>(path: string): Promise<T> {
  const url = path.startsWith("/api/") ? path : `${API_BASE}${path}`;
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `API error ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** Shared SWR defaults: dedupe within 2s, revalidate on focus. */
export const swrDefaults: SWRConfiguration = {
  revalidateOnFocus: true,
  dedupingInterval: 2000,
};

// ── Typed hooks ──────────────────────────────────────────────

interface Org {
  id: string;
  name: string;
  reporting_currency: string;
}

export function useOrgs() {
  const { data, error, isLoading, mutate } = useSWR<Org[]>(
    "/orgs",
    fetcher,
    swrDefaults
  );
  return {
    orgs: data ?? [],
    orgsLoading: isLoading,
    orgsError: error,
    refreshOrgs: () => mutate(),
  };
}

// ── Accounting periods (monthly containers) ──────────────────

export interface AccountingPeriod {
  id: string;
  org_id: string;
  period: string; // "2026-07"
  label: string; // "July 2026"
  status: string; // open | closed
}

/** GET /periods?org_id — an org's months, newest first. */
export function usePeriods(orgId: string) {
  const key = orgId ? `/periods?org_id=${orgId}` : null;
  const { data, error, isLoading, mutate } = useSWR<AccountingPeriod[]>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    periods: data ?? [],
    periodsLoading: isLoading,
    periodsError: error,
    refreshPeriods: () => mutate(),
  };
}

// ── Invoice Processing — disabled until Phase 2 ──────────────
// The invoice endpoints are not ready, so the hook below is intentionally
// removed to avoid broken API calls / error states on the dashboard. The
// Invoice Processing page is a static "Coming in Phase 2" placeholder.
//
// interface InvoiceListItem { ... }
// export function useInvoices(orgId, statusFilter, reviewFilter) { ... }

export interface SupplierReady {
  id: string;
  name: string;
  vendor_code: string;
  erp_count: number;
  statement_rows: number;
  has_erp: boolean;
  has_statement: boolean;
  ready: boolean;
  last_match_rate: number | null;
  last_run_status: string | null;
  // Review-queue breakdown for the latest run (0 if no run yet).
  total_lines: number;
  pending_review: number;
  confirmed: number;
  rejected: number;
  unmatched: number;
  near_exact_count: number;
  has_near_exact: boolean;
}

export function useSuppliers(orgId: string, period: string) {
  const key = orgId && period
    ? `/reconciliation/suppliers-ready?org_id=${orgId}&period=${period}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<SupplierReady[]>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    suppliers: data ?? [],
    suppliersLoading: isLoading,
    suppliersError: error,
    refreshSuppliers: () => mutate(),
  };
}

// ── Review queue ─────────────────────────────────────────────

export interface ReviewItem {
  id: string;
  match_type: string;
  status: string;
  discrepancy_type: string | null;
  quantity_delta: number | null;
  price_delta: number | null;
  amount_delta: number | null;
  confidence: number | null;
  confidence_score: number;
  confidence_label: string | null;
  sort_priority: number;
  discrepancy_note: string | null;
  amount: number | null;
  reviewer_id: string | null;
  match_details: Record<string, unknown> | null;
}

// The review queue is fetched directly in the reconciliation page (local state)
// so it can be refreshed precisely after a run and after each approve/reject.
// Endpoint: GET /api/v1/reconciliation/{supplierId}/{period}

// ── Dashboard ────────────────────────────────────────────────

export type SupplierStatus =
  | "matched"
  | "discrepancy"
  | "in_review"
  | "pending"
  | "error";

export interface DashboardSupplier {
  vendor_code: string;
  name: string;
  display_name: string;
  pinyin: string;
  status: SupplierStatus;
  erp_total: number | null;
  statement_total: number | null;
  discrepancy_value: number | null;
  discrepancy_details: string | null;
  action_required: "review" | "upload" | "none";
}

/** GET /api/suppliers — full supplier overview for the dashboard. */
export function useSupplierOverview() {
  const { data, error, isLoading, mutate } = useSWR<DashboardSupplier[]>(
    "/api/suppliers",
    fetcher,
    swrDefaults
  );
  return {
    suppliers: data ?? [],
    suppliersLoading: isLoading,
    suppliersError: error as Error | undefined,
    refreshSuppliers: () => mutate(),
  };
}

// GET /api/invoices/missing-count — removed for Phase 2.
// This endpoint does not exist yet; calling it produced the broken
// "Invoices Missing — Could not load invoice count." dashboard error state.
// The dashboard now shows a static "Coming in Phase 2" placeholder instead.
//
// export function useMissingInvoiceCount() { ... }

interface SideRecord {
  po_number: string | null;
  material_number: string | null;
  quantity: number;
  po_price?: number;
  unit_price?: number;
  amount: number;
  grn_date?: string | null;
  delivery_date?: string | null;
}

interface MismatchItem {
  id: string;
  match_type: string;
  status: string;
  discrepancy_type: string | null;
  quantity_delta: number | null;
  price_delta: number | null;
  amount_delta: number | null;
  confidence: number | null;
  resolution_note: string | null;
  erp: SideRecord | null;
  statement: SideRecord | null;
}

interface SupplierMismatch {
  supplier_id: string;
  supplier_name: string;
  vendor_code: string;
  run_id: string;
  match_rate: number | null;
  total_erp: number;
  total_statement: number;
  total_mismatches: number;
  unmatched_erp: number;
  unmatched_stmt: number;
  qty_issues: number;
  price_issues: number;
  items: MismatchItem[];
}

export function useMismatches(orgId: string, period: string) {
  const key = orgId && period
    ? `/reconciliation/mismatches?org_id=${orgId}&period=${period}`
    : null;
  const { data, error, isLoading, mutate } = useSWR<SupplierMismatch[]>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    data: data ?? [],
    mismatchesLoading: isLoading,
    mismatchesError: error,
    refreshMismatches: () => mutate(),
  };
}

interface ReconConfig {
  org_id: string;
  qty_tolerance_pct: number;
  price_tolerance_pct: number;
  auto_resolve_exact: boolean;
  ai_layer_enabled: boolean;
  ai_max_tokens_per_run: number;
}

export function useReconConfig(orgId: string) {
  const key = orgId ? `/reconciliation/config?org_id=${orgId}` : null;
  const { data, error, isLoading, mutate } = useSWR<ReconConfig | null>(
    key,
    async (path: string) => {
      const url = `${API_BASE}${path}`;
      const res = await fetch(url);
      if (!res.ok) return null;
      return res.json();
    },
    swrDefaults
  );
  return {
    config: data ?? null,
    configLoading: isLoading,
    configError: error,
    refreshConfig: () => mutate(),
  };
}
