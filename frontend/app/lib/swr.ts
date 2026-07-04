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
  role: "admin" | "accountant";
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

/** True when the current user may perform admin actions (sign-off, escalation review). */
export function useIsAdmin(): boolean {
  const { me } = useMe();
  return me?.role === "admin" || !!me?.is_superuser;
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

/**
 * GET /api/v1/reconciliation/dashboard — full supplier overview for the
 * dashboard. Pass the globally selected period; when empty (first paint,
 * nothing chosen yet) the backend auto-selects the latest period with data.
 */
export function useSupplierOverview(period?: string) {
  const key = period
    ? `/reconciliation/dashboard?period=${period}`
    : "/reconciliation/dashboard";
  const { data, error, isLoading, mutate } = useSWR<DashboardSupplier[]>(
    key,
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
  total_matches?: number;
  unmatched_erp: number;
  unmatched_stmt: number;
  qty_issues: number;
  price_issues: number;
  items: MismatchItem[];
}

export function useMismatches(orgId: string, period: string, includeMatches = false) {
  const key = orgId && period
    ? `/reconciliation/mismatches?org_id=${orgId}&period=${period}${includeMatches ? "&include_matches=true" : ""}`
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

// ── Notifications ────────────────────────────────────────────

export type NotificationType =
  | "escalation_created"
  | "escalation_acknowledged"
  | "escalation_resolved"
  | "period_signed_off"
  | "period_reopened";

export interface AppNotification {
  id: string;
  type: NotificationType;
  payload: Record<string, string> | null;
  escalation_id: string | null;
  org_id: string | null;
  period: string | null;
  read_at: string | null;
  created_at: string;
}

interface NotificationListPayload {
  items: AppNotification[];
  unread_count: number;
}

/** The bell's data source: latest notifications + unread count, polled every 30s. */
export function useNotifications() {
  const { data, error, isLoading, mutate } = useSWR<NotificationListPayload>(
    "/notifications?limit=20",
    fetcher,
    { ...swrDefaults, refreshInterval: 30000 }
  );

  async function markRead(id: string) {
    await fetch(`${API_BASE}/notifications/${id}/read`, {
      method: "POST",
      credentials: "include",
    });
    mutate();
  }

  async function markAllRead() {
    await fetch(`${API_BASE}/notifications/read-all`, {
      method: "POST",
      credentials: "include",
    });
    mutate();
  }

  return {
    notifications: data?.items ?? [],
    unreadCount: data?.unread_count ?? 0,
    notificationsLoading: isLoading,
    notificationsError: error,
    markRead,
    markAllRead,
    refreshNotifications: () => mutate(),
  };
}

// ── Accounting periods ───────────────────────────────────────

export interface PeriodInfo {
  period: string;
  label: string;
  has_data: boolean;
  locked: boolean;
}

/** Distinct periods for the org (derived from data + current month), newest first. */
export function usePeriods(orgId: string) {
  const { data, error, isLoading, mutate } = useSWR<PeriodInfo[]>(
    orgId ? `/periods?org_id=${orgId}` : null,
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

// ── Team management ──────────────────────────────────────────

export interface TeamMember {
  id: string;
  email: string;
  full_name: string | null;
  role: "admin" | "accountant";
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
}

/** Admin-only: the account's users. Non-admins get a 403 → key stays null via `enabled`. */
export function useTeam(enabled: boolean) {
  const { data, error, isLoading, mutate } = useSWR<TeamMember[]>(
    enabled ? "/users" : null,
    fetcher,
    swrDefaults
  );
  return {
    team: data ?? [],
    teamLoading: isLoading,
    teamError: error,
    refreshTeam: () => mutate(),
  };
}

// ── Period sign-off ──────────────────────────────────────────

export interface SignoffStatus {
  locked: boolean;
  status: "signed_off" | "reopened" | null;
  signed_off_by_name: string | null;
  signed_off_at: string | null;
  note: string | null;
  reopened_by_name: string | null;
  reopened_at: string | null;
  reopen_note: string | null;
}

/** Sign-off/lock state for an org+period. `locked` gates mutating UI. */
export function useSignoff(orgId: string, period: string) {
  const key =
    orgId && period ? `/signoffs?org_id=${orgId}&period=${period}` : null;
  const { data, error, isLoading, mutate } = useSWR<SignoffStatus>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    locked: data?.locked ?? false,
    signoff: data ?? null,
    signoffLoading: isLoading,
    signoffError: error,
    refreshSignoff: () => mutate(),
  };
}

// ── Escalations ──────────────────────────────────────────────

export interface EscalationItem {
  id: string;
  org_id: string;
  supplier_id: string | null;
  supplier_name: string | null;
  result_id: string | null;
  period: string;
  title: string;
  description: string | null;
  status: "open" | "acknowledged" | "resolved";
  raised_by_name: string | null;
  acknowledged_by_name: string | null;
  acknowledged_at: string | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
  created_at: string;
}

export function useEscalations(
  orgId: string,
  filters?: { period?: string; status?: string }
) {
  const params = new URLSearchParams();
  if (orgId) params.set("org_id", orgId);
  if (filters?.period) params.set("period", filters.period);
  if (filters?.status) params.set("status", filters.status);
  const key = orgId ? `/escalations?${params.toString()}` : null;
  const { data, error, isLoading, mutate } = useSWR<EscalationItem[]>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    escalations: data ?? [],
    escalationsLoading: isLoading,
    escalationsError: error,
    refreshEscalations: () => mutate(),
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
  // org_id is a PATH segment (matches the backend route /config/{org_id}).
  // The endpoint returns defaults when no config row exists, so it never
  // legitimately 404s — use the standard fetcher so real errors surface
  // instead of being swallowed as "no config".
  const key = orgId ? `/reconciliation/config/${orgId}` : null;
  const { data, error, isLoading, mutate } = useSWR<ReconConfig>(
    key,
    fetcher,
    swrDefaults
  );
  return {
    config: data ?? null,
    configLoading: isLoading,
    configError: error,
    refreshConfig: () => mutate(),
  };
}
