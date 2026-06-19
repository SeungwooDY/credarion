/**
 * SWR fetcher and shared hooks for Credarion.
 * Data is cached client-side and revalidated in the background,
 * so page navigations are instant after the first load.
 */
import useSWR, { type SWRConfiguration } from "swr";

const API_BASE = "/api/v1";

/**
 * Bounce the browser to the login page when the session is missing/expired.
 * Guards against redirect loops by ignoring calls already on /login.
 */
function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const next = encodeURIComponent(
    window.location.pathname + window.location.search,
  );
  window.location.assign(`/login?next=${next}`);
}

/** Default fetcher: prepends API_BASE, throws on non-ok responses. */
export async function fetcher<T = unknown>(path: string): Promise<T> {
  const url = path.startsWith("/api/") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, { credentials: "include" });
  if (res.status === 401) {
    redirectToLogin();
    throw new Error("Not authenticated");
  }
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

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  is_superuser: boolean;
  account: {
    id: string;
    name: string;
    plan: string;
    subscription_status: string;
  };
  organizations: Org[];
}

/** Current authenticated user + their account and accessible organizations. */
export function useMe() {
  const { data, error, isLoading, mutate } = useSWR<Me>(
    "/auth/me",
    fetcher,
    { ...swrDefaults, shouldRetryOnError: false },
  );
  return {
    me: data ?? null,
    meLoading: isLoading,
    meError: error,
    refreshMe: () => mutate(),
  };
}

/**
 * The logged-in user's organization. Since each user belongs to one account
 * and (for now) operates a single entity, this is just the first org returned
 * by /auth/me — there is no org picker anymore.
 */
export function useCurrentOrg() {
  const { me, meLoading } = useMe();
  const org = me?.organizations?.[0] ?? null;
  return {
    orgId: org?.id ?? "",
    org,
    orgName: org?.name ?? "",
    orgLoading: meLoading,
  };
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

interface InvoiceListItem {
  id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  total_amount: number | null;
  currency: string;
  status: string;
  supplier_name_extracted: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  created_at: string;
}

export function useInvoices(orgId: string, statusFilter: string, reviewFilter: string) {
  let key: string | null = null;
  if (orgId) {
    key = `/invoices/?org_id=${orgId}&limit=100`;
    if (statusFilter) key += `&status=${statusFilter}`;
    if (reviewFilter) key += `&needs_review=${reviewFilter}`;
  }
  const { data, error, isLoading, mutate } = useSWR<InvoiceListItem[]>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    invoices: data ?? [],
    invoicesLoading: isLoading,
    invoicesError: error,
    refreshInvoices: () => mutate(),
  };
}

interface SupplierReady {
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
