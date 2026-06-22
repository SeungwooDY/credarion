"use client";

import Link from "next/link";
import { getLocalTimeZone } from "@internationalized/date";
import PageHeader from "./components/page-header";
import NotificationBell, {
  type DashboardNotification,
} from "./components/notification-bell";
import { RoadmapCard, type RoadmapItem } from "@/components/ui/roadmap-card";
import { CloseDatePicker } from "@/components/ui/close-date-picker";
import { CARD } from "./lib/ui";
import { useCloseDate } from "./lib/close-date";
import { useT } from "./lib/i18n";
import {
  useSupplierOverview,
  type DashboardSupplier,
  type SupplierStatus,
} from "./lib/swr";

const ACCENT = "#4169E1";

// ── Helpers ──────────────────────────────────────────────────

function formatCNY(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `¥${n.toLocaleString("en-US")}`;
}

/** Dictionary key for the queue description when the API gives no detail text. */
function fallbackKey(status: SupplierStatus): string {
  switch (status) {
    case "pending":
      return "dashboard.fallback.pending";
    case "error":
      return "dashboard.fallback.error";
    case "in_review":
      return "dashboard.fallback.in_review";
    case "discrepancy":
      return "dashboard.fallback.discrepancy";
    default:
      return "dashboard.fallback.matched";
  }
}

/** Maps a status to the action-queue dot colour (red = urgent, amber = waiting, green = done). */
function dotColor(status: SupplierStatus): string {
  if (status === "discrepancy") return "bg-red-500";
  if (status === "matched") return "bg-green-500";
  return "bg-amber-400";
}

const STATUS_PILL: Record<SupplierStatus, string> = {
  matched: "bg-green-50 text-green-700",
  discrepancy: "bg-red-50 text-red-600",
  in_review: "bg-amber-50 text-amber-700",
  pending: "bg-gray-100 text-gray-500",
  error: "bg-red-50 text-red-600",
};

// ── Primitive components ─────────────────────────────────────

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-gray-200 ${className}`} />;
}

const LABEL = "text-xs uppercase tracking-wide text-gray-400";

function NoData() {
  const t = useT();
  return <div className="text-sm text-gray-400">{t("dashboard.no_data")}</div>;
}

function StatusPill({ status }: { status: SupplierStatus }) {
  const t = useT();
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_PILL[status]}`}
    >
      {t(`common.status.${status}`)}
    </span>
  );
}

/** Action control shared by the queue and table. */
function ActionControl({
  action,
  size = "sm",
}: {
  action: DashboardSupplier["action_required"];
  size?: "sm" | "xs";
}) {
  const t = useT();
  if (action === "none") {
    return (
      <span className="inline-flex items-center justify-center text-gray-300" aria-label="Done">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </span>
    );
  }
  const isUpload = action === "upload";
  const label = isUpload ? t("common.upload") : t("common.review");
  const href = isUpload ? "/ingestion" : "/mismatches";
  const pad = size === "xs" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-xs";
  return (
    <Link
      href={href}
      className={`inline-flex items-center rounded-md font-medium text-white no-underline transition-opacity hover:opacity-90 ${pad}`}
      style={{ backgroundColor: ACCENT }}
    >
      {label}
    </Link>
  );
}

// ── Section 1: Stat cards ────────────────────────────────────

function StatCard({
  label,
  children,
  subtext,
  action,
}: {
  label: string;
  children: React.ReactNode;
  subtext?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className={`${CARD} relative p-4`}>
      {action && <div className="absolute right-2.5 top-2.5">{action}</div>}
      <div className={LABEL}>{label}</div>
      <div className="mt-2">{children}</div>
      {subtext != null && (
        <div className="mt-1.5 text-xs text-gray-400">{subtext}</div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────

export default function DashboardPage() {
  const t = useT();
  const { suppliers, suppliersLoading, suppliersError } = useSupplierOverview();

  // Month-end close date (user-configurable, persisted) + countdown.
  // Client-only to avoid hydration drift.
  const { closeDate, daysLeft, setCloseDate } = useCloseDate();
  const closeLabel = closeDate
    ? closeDate
        .toDate(getLocalTimeZone())
        .toLocaleDateString(undefined, { month: "short", day: "numeric" })
    : null;

  // Derived metrics from the supplier array.
  const total = suppliers.length;
  const matched = suppliers.filter((s) => s.status === "matched").length;
  const pendingReview = total - matched;
  const discrepancySuppliers = suppliers.filter((s) => s.status === "discrepancy");
  const discrepancyValue = discrepancySuppliers.reduce(
    (sum, s) => sum + (s.discrepancy_value ?? 0),
    0
  );
  const matchedPct = total > 0 ? (matched / total) * 100 : 0;

  // Suppliers whose statement hasn't been uploaded yet never get a row — they'd
  // bury the dashboard under hundreds of un-actionable lines. The count is
  // flagged via the notification bell instead. The list views stay focused on
  // suppliers with real, money-bearing discrepancies (already sorted
  // hottest-first by the backend).
  const isAwaitingUpload = (s: DashboardSupplier) => s.action_required === "upload";
  const overviewSuppliers = suppliers.filter((s) => !isAwaitingUpload(s));
  const queue = overviewSuppliers.filter((s) => s.status !== "matched");
  const awaitingUploadCount = suppliers.filter(isAwaitingUpload).length;

  // Dashboard notifications (bell, top-right). The only flag right now is the
  // pile of suppliers still missing statements; it turns urgent ≤5 days to close.
  const closeIsNear = daysLeft != null && daysLeft <= 5;
  const notifications: DashboardNotification[] = [];
  if (awaitingUploadCount > 0) {
    notifications.push({
      id: "awaiting-upload",
      title: t("dashboard.notif.awaiting_upload", { n: awaitingUploadCount }),
      detail:
        closeIsNear && daysLeft != null
          ? t("dashboard.notif.awaiting_upload_urgent", { days: daysLeft })
          : t("dashboard.notif.awaiting_upload_sub"),
      tone: closeIsNear ? "urgent" : "warning",
      href: "/ingestion",
    });
  }

  // Once loading settles, treat both a fetch failure and an empty result as
  // simply "no data" — the dashboard stays calm instead of showing red errors.
  const noSupplierData = !suppliersLoading && (Boolean(suppliersError) || total === 0);

  // Month-end close pipeline. Supplier Reconciliation is the live stage (shows
  // matched/total); the rest unlock sequentially and stay "Not Started" for now.
  const closeLoading = suppliersLoading && total === 0;
  const closeStages: RoadmapItem[] = [
    {
      quarter: t("dashboard.step", { n: 1 }),
      title: t("dashboard.stage.supplier_recon"),
      description: closeLoading
        ? t("common.loading")
        : t("dashboard.stage_complete", { n: matched, total }),
      status: "in-progress",
    },
    {
      quarter: t("dashboard.step", { n: 2 }),
      title: t("dashboard.stage.discrepancy_resolution"),
      description: t("dashboard.not_started"),
      status: "upcoming",
    },
    {
      quarter: t("dashboard.step", { n: 3 }),
      title: t("dashboard.stage.cfo_signoff"),
      description: t("dashboard.not_started"),
      status: "upcoming",
    },
  ];

  const daysColor =
    daysLeft === null
      ? "text-gray-800"
      : daysLeft <= 5
        ? "text-red-600"
        : daysLeft <= 10
          ? "text-amber-500"
          : "text-gray-800";

  return (
    <div className="animate-fade-in-up">
      <PageHeader
        title={t("dashboard.title")}
        description={t("dashboard.subtitle")}
        action={
          <NotificationBell
            notifications={notifications}
            title={t("dashboard.notif.title")}
            emptyLabel={t("dashboard.notif.empty")}
          />
        }
      />

      {/* ── Section 1: Stat cards ── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* Card 1 — Suppliers Reconciled */}
        <StatCard
          label={t("dashboard.card.suppliers_reconciled")}
          subtext={
            suppliersLoading ? (
              <Skeleton className="h-3 w-24" />
            ) : noSupplierData ? null : (
              t("dashboard.pending_review", { n: pendingReview })
            )
          }
        >
          {suppliersLoading ? (
            <Skeleton className="h-9 w-28" />
          ) : noSupplierData ? (
            <NoData />
          ) : (
            <>
              <div className="text-3xl font-bold text-gray-800">
                {matched} / {total}{" "}
                <span className="text-sm font-medium text-gray-400">{t("dashboard.this_month")}</span>
              </div>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-100">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${matchedPct}%`, backgroundColor: ACCENT }}
                />
              </div>
            </>
          )}
        </StatCard>

        {/* Card 2 — Unresolved Discrepancy Value */}
        <StatCard
          label={t("dashboard.card.discrepancy_value")}
          subtext={
            suppliersLoading ? (
              <Skeleton className="h-3 w-24" />
            ) : noSupplierData ? null : (
              t("dashboard.across_suppliers", { n: discrepancySuppliers.length })
            )
          }
        >
          {suppliersLoading ? (
            <Skeleton className="h-9 w-28" />
          ) : noSupplierData ? (
            <NoData />
          ) : (
            <div
              className={`text-3xl font-bold ${discrepancyValue > 0 ? "text-red-600" : "text-green-600"}`}
            >
              {formatCNY(discrepancyValue)}
            </div>
          )}
        </StatCard>

        {/* Card 3 — Invoice Processing (static placeholder, Phase 2) */}
        <StatCard label={t("dashboard.card.invoices")}>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-gray-300">—</span>
            <span className="inline-flex rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
              {t("dashboard.invoices_phase2")}
            </span>
          </div>
        </StatCard>

        {/* Card 4 — Days to Month-End Close */}
        <StatCard
          label={t("dashboard.card.days_to_close")}
          subtext={
            closeLabel ? (
              t("dashboard.closes_on", { date: closeLabel })
            ) : (
              <Skeleton className="h-3 w-24" />
            )
          }
          action={
            <CloseDatePicker
              value={closeDate}
              onChange={setCloseDate}
              label={t("dashboard.set_close_date")}
            />
          }
        >
          {daysLeft === null ? (
            <Skeleton className="h-9 w-28" />
          ) : (
            <div className={`text-3xl font-bold ${daysColor}`}>
              {daysLeft}{" "}
              <span className="text-sm font-medium text-gray-400">
                {t("dashboard.days")}
              </span>
            </div>
          )}
        </StatCard>
      </div>

      {/* ── Section 2: Action queue ── */}
      <div className={`${CARD} mt-6`}>
        <div className="border-b border-gray-100 px-5 py-4">
          <h3 className="text-base font-semibold text-gray-800">{t("dashboard.needs_attention")}</h3>
        </div>

        {suppliersLoading ? (
          <div>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex items-center gap-3 border-b border-gray-100 px-5 py-4 last:border-b-0">
                <Skeleton className="h-2.5 w-2.5 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-40" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
                <Skeleton className="h-7 w-16" />
              </div>
            ))}
          </div>
        ) : noSupplierData ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">
            {t("dashboard.no_data")}
          </div>
        ) : queue.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">
            {t("dashboard.all_reconciled")}
          </div>
        ) : (
          <div>
            {queue.map((s) => (
              <div
                key={s.vendor_code}
                className="flex items-center gap-3 border-b border-gray-100 px-5 py-4 transition-colors last:border-b-0 hover:bg-gray-50"
              >
                <span className={`mt-1 h-2.5 w-2.5 shrink-0 self-start rounded-full ${dotColor(s.status)}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-gray-800">
                    {s.display_name}{" "}
                    <span className="font-normal text-gray-400">[{s.pinyin}]</span>
                  </div>
                  <div className="mt-0.5 text-sm text-gray-600">
                    {s.discrepancy_details ?? t(fallbackKey(s.status))}
                  </div>
                </div>
                <div className="shrink-0">
                  <ActionControl action={s.action_required} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Section 3: Month-end close progress ── */}
      <RoadmapCard
        className="mt-6"
        title={t("dashboard.close_progress_title")}
        description={
          closeLoading
            ? t("common.loading")
            : t("dashboard.close_progress_note", { matched, total })
        }
        items={closeStages}
      />

      {/* ── Section 4: Supplier overview table ── */}
      <div className={`${CARD} mt-6`}>
        <div className="border-b border-gray-100 px-5 py-4">
          <h3 className="text-base font-semibold text-gray-800">{t("dashboard.supplier_overview")}</h3>
        </div>

        {noSupplierData ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">
            {t("dashboard.no_data")}
          </div>
        ) : !suppliersLoading && overviewSuppliers.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-gray-400">
            {t("dashboard.all_reconciled")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase tracking-wide text-gray-400">
                  <th className="px-5 py-3 text-left font-medium">{t("dashboard.col.supplier")}</th>
                  <th className="px-5 py-3 text-left font-medium">{t("dashboard.col.status")}</th>
                  <th className="px-5 py-3 text-right font-medium">{t("dashboard.col.erp_total")}</th>
                  <th className="px-5 py-3 text-right font-medium">{t("dashboard.col.statement_total")}</th>
                  <th className="px-5 py-3 text-right font-medium">{t("dashboard.col.discrepancy")}</th>
                  <th className="px-5 py-3 text-right font-medium">{t("dashboard.col.action")}</th>
                </tr>
              </thead>
              <tbody>
                {suppliersLoading ? (
                  [0, 1, 2, 3, 4].map((i) => (
                    <tr key={i} className="border-t border-gray-100">
                      <td className="px-5 py-3"><Skeleton className="h-4 w-32" /></td>
                      <td className="px-5 py-3"><Skeleton className="h-5 w-20 rounded-full" /></td>
                      <td className="px-5 py-3"><Skeleton className="ml-auto h-4 w-20" /></td>
                      <td className="px-5 py-3"><Skeleton className="ml-auto h-4 w-20" /></td>
                      <td className="px-5 py-3"><Skeleton className="ml-auto h-4 w-16" /></td>
                      <td className="px-5 py-3"><Skeleton className="ml-auto h-7 w-16" /></td>
                    </tr>
                  ))
                ) : (
                  overviewSuppliers.map((s) => {
                    const hasDiscrepancy = (s.discrepancy_value ?? 0) > 0;
                    return (
                      <tr
                        key={s.vendor_code}
                        className="border-t border-gray-100 transition-colors hover:bg-gray-50"
                      >
                        <td className="px-5 py-3 font-medium text-gray-800">
                          {s.display_name}{" "}
                          <span className="font-normal text-gray-400">[{s.pinyin}]</span>
                        </td>
                        <td className="px-5 py-3">
                          <StatusPill status={s.status} />
                        </td>
                        <td className="px-5 py-3 text-right font-mono text-gray-700">
                          {formatCNY(s.erp_total)}
                        </td>
                        <td className="px-5 py-3 text-right font-mono text-gray-700">
                          {formatCNY(s.statement_total)}
                        </td>
                        <td
                          className={`px-5 py-3 text-right font-mono ${hasDiscrepancy ? "text-red-600" : "text-gray-400"}`}
                        >
                          {hasDiscrepancy ? formatCNY(s.discrepancy_value) : "—"}
                        </td>
                        <td className="px-5 py-3 text-right">
                          <ActionControl action={s.action_required} size="xs" />
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

