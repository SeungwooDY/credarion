"use client";

import { useEffect, useState, useRef } from "react";
import { ChevronDown, ChevronRight, Check, Flag } from "lucide-react";
import PageHeader from "../components/page-header";
import { useOrgs, useSuppliers, type ReviewItem, type SupplierReady } from "../lib/swr";
import { CARD } from "@/app/lib/ui";
import { useT, type TFunction } from "@/app/lib/i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// Identifier recorded against confirm/flag actions (no auth layer yet).
const REVIEWER_ID = "accountant";

interface RunResult {
  run: {
    id: string;
    status: string;
    total_erp: number;
    total_statement: number;
    matched_count: number;
    discrepancy_count: number;
    unmatched_count: number;
    erp_not_in_statement: number;
    auto_match_rate: number | null;
  };
}

// ── Review queue section config (drives ordering, colour, behaviour) ──
interface SectionDef {
  priority: number;
  labelKey: string;
  border: string;
  confirmAll?: boolean;
  showNote?: boolean;
  readOnly?: boolean;
  defaultCollapsed: (count: number) => boolean;
}

const SECTIONS: SectionDef[] = [
  { priority: 1, labelKey: "review.section.exact", border: "border-l-green-500", confirmAll: true, defaultCollapsed: (n) => n > 30 },
  { priority: 2, labelKey: "review.section.near_exact", border: "border-l-amber-500", showNote: true, defaultCollapsed: () => false },
  { priority: 3, labelKey: "review.section.fuzzy", border: "border-l-zinc-300", defaultCollapsed: () => true },
  { priority: 4, labelKey: "review.section.aggregated", border: "border-l-zinc-300", defaultCollapsed: () => true },
  { priority: 5, labelKey: "review.section.ai", border: "border-l-orange-500", defaultCollapsed: () => false },
  { priority: 6, labelKey: "review.section.unmatched", border: "border-l-red-500", readOnly: true, defaultCollapsed: () => false },
];

const PROGRESS_PHRASE_KEYS = [
  "reconciliation.progress_loading",
  "reconciliation.progress_normalizing",
  "reconciliation.progress_layer1",
  "reconciliation.progress_layer2",
  "reconciliation.progress_layer3",
  "reconciliation.progress_layer4",
  "reconciliation.progress_classifying",
  "reconciliation.progress_match_rate",
  "reconciliation.progress_finalizing",
];

function formatAmount(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `¥${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function strField(d: Record<string, unknown> | null, key: string): string | null {
  if (d && typeof d[key] === "string") return d[key] as string;
  return null;
}

function ThinkingIndicator({ supplierName }: { supplierName: string }) {
  const t = useT();
  const [phraseIndex, setPhraseIndex] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setPhraseIndex((prev) =>
        prev < PROGRESS_PHRASE_KEYS.length - 1 ? prev + 1 : prev
      );
    }, 2200);
    return () => clearInterval(timerRef.current);
  }, []);

  return (
    <div className="my-8 flex justify-center">
      <div className="bg-accent-light rounded-2xl px-6 py-5 max-w-md w-full">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-bold bg-accent">
            C
          </div>
          <span className="text-sm font-medium text-zinc-700">
            {t("reconciliation.reconciling_name", { name: supplierName })}
          </span>
          <div className="thinking-dots ml-auto flex gap-1">
            <span /><span /><span />
          </div>
        </div>
        <div className="space-y-1.5 pl-10">
          {PROGRESS_PHRASE_KEYS.slice(0, phraseIndex + 1).map((phraseKey, i) => (
            <div
              key={i}
              className={`text-sm animate-fade-in-up ${
                i === phraseIndex ? "text-accent font-medium" : "text-zinc-400"
              }`}
            >
              {i < phraseIndex && (
                <svg className="inline w-3.5 h-3.5 mr-1.5 text-green-500 -mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
              {i === phraseIndex && <span className="inline-block w-3.5 mr-1.5" />}
              {t(phraseKey)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── A single review line item ──
function ReviewRow({
  item,
  showNote,
  readOnly,
  busy,
  onConfirm,
  onFlag,
  t,
}: {
  item: ReviewItem;
  showNote?: boolean;
  readOnly?: boolean;
  busy: boolean;
  onConfirm: (id: string) => void;
  onFlag: (item: ReviewItem) => void;
  t: TFunction;
}) {
  const po = strField(item.match_details, "po");
  const pn = strField(item.match_details, "pn");
  const reviewed = item.status === "confirmed" || item.status === "rejected";

  return (
    <div
      className={`px-4 py-3 ${reviewed ? "opacity-60" : ""}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-medium text-zinc-800">
              {po ? `${t("review.po")} ${po}` : t("review.no_pair")}
            </span>
            {pn && <span className="text-xs text-zinc-400">· {pn}</span>}
            {item.confidence_label && (
              <span className="text-[11px] text-zinc-400">{item.confidence_label}</span>
            )}
          </div>
          <div className="mt-1 flex items-center gap-4 text-xs text-zinc-500 flex-wrap">
            <span className="font-mono">{formatAmount(item.amount)}</span>
            {item.quantity_delta != null && item.quantity_delta !== 0 && (
              <span>{t("reconciliation.qty_delta")}: <span className="font-mono text-amber-600">{item.quantity_delta.toFixed(2)}</span></span>
            )}
            {item.price_delta != null && item.price_delta !== 0 && (
              <span>{t("reconciliation.price_delta")}: <span className="font-mono text-amber-600">{item.price_delta.toFixed(4)}</span></span>
            )}
          </div>
          {showNote && item.discrepancy_note && (
            <div className="mt-2 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
              {item.discrepancy_note}
            </div>
          )}
        </div>

        <div className="shrink-0">
          {reviewed ? (
            <Badge variant="secondary" className={item.status === "confirmed" ? "text-green-700" : "text-red-600"}>
              {item.status === "confirmed" ? t("review.confirmed") : t("review.flagged")}
            </Badge>
          ) : readOnly ? (
            <span className="text-xs text-zinc-400">—</span>
          ) : (
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onConfirm(item.id)}
                className="h-8 gap-1.5 border-green-300 text-green-700 hover:bg-green-50"
              >
                <Check className="h-3.5 w-3.5" /> {t("review.confirm_match")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onFlag(item)}
                className="h-8 gap-1.5 border-amber-300 text-amber-700 hover:bg-amber-50"
              >
                <Flag className="h-3.5 w-3.5" /> {t("review.flag_discrepancy")}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Reject reason modal ──
function RejectModal({
  open,
  onClose,
  onSubmit,
  busy,
  t,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
  busy: boolean;
  t: TFunction;
}) {
  // Fresh state each time it opens — the parent remounts via `key`.
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);

  if (!open) return null;
  const empty = reason.trim().length === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className={`${CARD} w-full max-w-md p-5 shadow-lg`} onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-semibold text-zinc-800">{t("review.modal.title")}</h3>
        <p className="mt-1 text-sm text-zinc-500">{t("review.modal.subtitle")}</p>
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          onBlur={() => setTouched(true)}
          rows={4}
          placeholder={t("review.modal.placeholder")}
          className="mt-3 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
        />
        {touched && empty && (
          <p className="mt-1 text-xs text-red-600">{t("review.modal.reason_required")}</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </Button>
          <Button
            size="sm"
            disabled={busy || empty}
            onClick={() => {
              setTouched(true);
              if (!empty) onSubmit(reason.trim());
            }}
            className="gap-1.5 bg-amber-600 text-white hover:bg-amber-700"
          >
            <Flag className="h-3.5 w-3.5" /> {t("review.flag_discrepancy")}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Supplier readiness/breakdown row ──
function SupplierRow({
  s,
  active,
  loading,
  selectedId,
  onRun,
  t,
}: {
  s: SupplierReady;
  active: boolean;
  loading: boolean;
  selectedId: string;
  onRun: (id: string) => void;
  t: TFunction;
}) {
  const hasRun = s.total_lines > 0;
  return (
    <tr
      className={`border-t border-border transition-colors ${
        active ? "bg-accent-light" : "hover:bg-muted"
      } ${!s.ready ? "opacity-50" : ""}`}
    >
      <td className="px-4 py-3">
        <div className="font-medium text-zinc-800">{s.name}</div>
        <div className="text-xs text-zinc-400 mt-0.5">{s.vendor_code}</div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-zinc-600">
        {s.erp_count > 0 ? s.erp_count : <span className="text-red-400">0</span>}
      </td>
      <td className="px-4 py-3 text-right font-mono text-zinc-600">
        {s.statement_rows > 0 ? (
          s.statement_rows
        ) : (
          <span className="text-red-400 text-xs font-sans">{t("reconciliation.missing")}</span>
        )}
      </td>
      <td className="px-4 py-3 text-center">
        {hasRun ? (
          <div className="flex flex-col items-center gap-1">
            <span className="text-xs text-zinc-600">
              {t("review.breakdown", {
                confirmed: s.confirmed,
                pending: s.pending_review,
                rejected: s.rejected,
              })}
            </span>
            {s.has_near_exact && (
              <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                {t("review.needs_attention", { n: s.near_exact_count })}
              </span>
            )}
          </div>
        ) : s.ready ? (
          <span className="inline-block text-xs px-2.5 py-0.5 rounded-full font-medium bg-accent-light text-accent">
            {t("reconciliation.ready")}
          </span>
        ) : (
          <span className="inline-block text-xs px-2.5 py-0.5 rounded-full bg-zinc-100 text-zinc-500">
            {!s.has_statement ? t("reconciliation.no_statement") : t("reconciliation.no_erp")}
          </span>
        )}
      </td>
      <td className="px-4 py-3 text-right font-mono">
        {s.last_match_rate != null ? (
          <span
            className={`font-semibold ${
              s.last_match_rate >= 90
                ? "text-green-600"
                : s.last_match_rate >= 50
                  ? "text-amber-600"
                  : "text-red-500"
            }`}
          >
            {s.last_match_rate.toFixed(1)}%
          </span>
        ) : (
          <span className="text-zinc-300">&mdash;</span>
        )}
      </td>
      <td className="px-4 py-3 text-center">
        <button
          onClick={() => onRun(s.id)}
          disabled={!s.ready || loading}
          className="px-3.5 py-1.5 text-xs font-medium text-white rounded-lg bg-accent hover:bg-accent-dark disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          {loading && selectedId === s.id ? t("reconciliation.running") : t("common.run")}
        </button>
      </td>
    </tr>
  );
}

export default function ReconciliationPage() {
  const t = useT();
  const { orgs } = useOrgs();
  const [orgId, setOrgId] = useState("");
  const [period, setPeriod] = useState("2026-03");
  const { suppliers, suppliersLoading, refreshSuppliers } = useSuppliers(orgId, period);

  const [supplierId, setSupplierId] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});
  const [reviewedCollapsed, setReviewedCollapsed] = useState(true);
  const [rejectTarget, setRejectTarget] = useState<ReviewItem | null>(null);

  useEffect(() => {
    if (orgs.length > 0 && !orgId) setOrgId(orgs[0].id);
  }, [orgs, orgId]);

  async function loadQueue(sid: string, initCollapse = false) {
    if (!sid || !period) return;
    const res = await fetch(`/api/v1/reconciliation/${sid}/${period}`);
    if (!res.ok) return;
    const data: ReviewItem[] = await res.json();
    setItems(data);
    if (initCollapse) {
      const next: Record<number, boolean> = {};
      for (const sec of SECTIONS) {
        const count = data.filter((i) => i.sort_priority === sec.priority).length;
        next[sec.priority] = sec.defaultCollapsed(count);
      }
      setCollapsed(next);
    }
  }

  async function runReconciliation(sid?: string) {
    const targetId = sid || supplierId;
    if (!targetId || !period) return;
    setLoading(true);
    setError("");
    setRunResult(null);
    setItems([]);
    setSupplierId(targetId);

    try {
      const res = await fetch("/api/v1/reconciliation/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ supplier_id: targetId, period }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || JSON.stringify(data));
        setLoading(false);
        return;
      }
      setRunResult(data);
      await loadQueue(targetId, true);
      refreshSuppliers();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setLoading(false);
  }

  async function confirmOne(id: string) {
    setBusy(true);
    try {
      await fetch(`/api/v1/reconciliation/${id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_id: REVIEWER_ID }),
      });
      await loadQueue(supplierId);
      refreshSuppliers();
    } catch {
      setError(t("review.action_failed"));
    }
    setBusy(false);
  }

  async function confirmAll(priority: number) {
    const ids = items
      .filter((i) => i.sort_priority === priority && i.status === "pending_review")
      .map((i) => i.id);
    if (ids.length === 0) return;
    setBusy(true);
    try {
      await Promise.all(
        ids.map((id) =>
          fetch(`/api/v1/reconciliation/${id}/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer_id: REVIEWER_ID }),
          })
        )
      );
      await loadQueue(supplierId);
      refreshSuppliers();
    } catch {
      setError(t("review.action_failed"));
    }
    setBusy(false);
  }

  async function submitReject(reason: string) {
    if (!rejectTarget) return;
    setBusy(true);
    try {
      await fetch(`/api/v1/reconciliation/${rejectTarget.id}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer_id: REVIEWER_ID, reason }),
      });
      setRejectTarget(null);
      await loadQueue(supplierId);
      refreshSuppliers();
    } catch {
      setError(t("review.action_failed"));
    }
    setBusy(false);
  }

  const selectedSupplier = suppliers.find((s) => s.id === supplierId);
  const readyCount = suppliers.filter((s) => s.ready).length;
  const notReadyCount = suppliers.filter((s) => !s.ready).length;

  // Progress (reviewable = matched pairs, excludes unmatched "no match found").
  const reviewable = items.filter((i) => i.match_type !== "unmatched");
  const confirmedCount = reviewable.filter((i) => i.status === "confirmed").length;
  const rejectedCount = reviewable.filter((i) => i.status === "rejected").length;
  const reviewedCount = confirmedCount + rejectedCount;
  const totalCount = reviewable.length;
  const pct = totalCount > 0 ? (reviewedCount / totalCount) * 100 : 0;

  const reviewedItems = items.filter((i) => i.status === "confirmed" || i.status === "rejected");

  return (
    <>
      <PageHeader
        title={t("reconciliation.title")}
        description={t("reconciliation.description")}
      />

      {/* Controls */}
      <div className="flex gap-4 items-end mb-6">
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1.5">{t("common.period")}</label>
          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="border border-border rounded-lg px-3 py-2 text-sm bg-card w-28 focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
          />
        </div>
      </div>

      {/* Supplier readiness + breakdown table */}
      <div className={`${CARD} overflow-hidden mb-6`}>
        <div className="bg-muted px-4 py-3 flex items-center justify-between border-b border-border">
          <h3 className="text-sm font-semibold text-zinc-700">
            {t("reconciliation.suppliers_for_period", { period })}
          </h3>
          {!suppliersLoading && (
            <div className="text-xs text-zinc-500">
              <span className="font-medium text-accent">{t("reconciliation.n_ready", { n: readyCount })}</span>
              {notReadyCount > 0 && (
                <span className="ml-2 text-zinc-400">
                  {t("reconciliation.n_missing_data", { n: notReadyCount })}
                </span>
              )}
            </div>
          )}
        </div>

        {suppliersLoading ? (
          <div className="p-6 text-sm text-zinc-400 text-center">{t("reconciliation.loading_suppliers")}</div>
        ) : suppliers.length === 0 ? (
          <div className="p-6 text-sm text-zinc-400 text-center">{t("reconciliation.no_suppliers")}</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-zinc-400 uppercase tracking-wider">
                <th className="text-left px-4 py-2.5 font-medium">{t("common.supplier")}</th>
                <th className="text-right px-4 py-2.5 font-medium">ERP</th>
                <th className="text-right px-4 py-2.5 font-medium">{t("reconciliation.statement")}</th>
                <th className="text-center px-4 py-2.5 font-medium">{t("common.status")}</th>
                <th className="text-right px-4 py-2.5 font-medium">{t("reconciliation.match_rate")}</th>
                <th className="text-center px-4 py-2.5 font-medium">{t("common.action")}</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <SupplierRow
                  key={s.id}
                  s={s}
                  active={s.id === supplierId}
                  loading={loading}
                  selectedId={supplierId}
                  onRun={runReconciliation}
                  t={t}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {loading && (
        <ThinkingIndicator supplierName={selectedSupplier?.name || t("reconciliation.supplier_fallback")} />
      )}

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-3 rounded-lg mb-4">
          {error}
        </div>
      )}

      {/* Review queue */}
      {items.length > 0 && !loading && (
        <>
          <h3 className="text-sm font-semibold mb-3 text-zinc-700">
            {t("review.queue_title", { name: selectedSupplier?.name || "" })}
          </h3>

          {/* Progress indicator */}
          <div className={`${CARD} p-4 mb-5`}>
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-600">
                {t("review.progress", {
                  reviewed: reviewedCount,
                  total: totalCount,
                  confirmed: confirmedCount,
                  rejected: rejectedCount,
                })}
              </span>
              <span className="font-mono text-xs text-zinc-400">{Math.round(pct)}%</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-zinc-100">
              <div className="h-full rounded-full bg-green-500 transition-all" style={{ width: `${pct}%` }} />
            </div>
          </div>

          {/* Sections */}
          <div className="space-y-4">
            {SECTIONS.map((sec) => {
              const sectionItems = items.filter(
                (i) => i.sort_priority === sec.priority && i.status !== "confirmed" && i.status !== "rejected"
              );
              if (sectionItems.length === 0) return null;
              const isCollapsed = collapsed[sec.priority] ?? false;
              const pendingInSection = sectionItems.filter((i) => i.status === "pending_review");

              return (
                <div key={sec.priority} className={`${CARD} overflow-hidden`}>
                  <div className="flex items-center justify-between bg-muted px-4 py-2.5 border-b border-border">
                    <button
                      className="flex items-center gap-2 text-sm font-semibold text-zinc-700"
                      onClick={() => setCollapsed((c) => ({ ...c, [sec.priority]: !isCollapsed }))}
                    >
                      {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                      {t(sec.labelKey, { count: sectionItems.length })}
                    </button>
                    {sec.confirmAll && pendingInSection.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => confirmAll(sec.priority)}
                        className="h-7 gap-1.5 border-green-300 text-green-700 hover:bg-green-50"
                      >
                        <Check className="h-3.5 w-3.5" /> {t("review.confirm_all")}
                      </Button>
                    )}
                  </div>
                  {!isCollapsed && (
                    <div className="divide-y divide-border">
                      {sectionItems.map((item) => (
                        <div key={item.id} className={`border-l-4 ${sec.border}`}>
                          <ReviewRow
                            item={item}
                            showNote={sec.showNote}
                            readOnly={sec.readOnly}
                            busy={busy}
                            onConfirm={confirmOne}
                            onFlag={(it) => setRejectTarget(it)}
                            t={t}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Reviewed (confirmed + flagged) */}
            {reviewedItems.length > 0 && (
              <div className={`${CARD} overflow-hidden`}>
                <button
                  className="flex w-full items-center gap-2 bg-muted px-4 py-2.5 border-b border-border text-sm font-semibold text-zinc-500"
                  onClick={() => setReviewedCollapsed((v) => !v)}
                >
                  {reviewedCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  {t("review.section.reviewed", { count: reviewedItems.length })}
                </button>
                {!reviewedCollapsed && (
                  <div className="divide-y divide-border">
                    {reviewedItems.map((item) => (
                      <div key={item.id} className="border-l-4 border-l-zinc-200">
                        <ReviewRow
                          item={item}
                          busy={busy}
                          onConfirm={confirmOne}
                          onFlag={(it) => setRejectTarget(it)}
                          t={t}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {items.length === 0 && runResult && !loading && (
        <div className="text-sm text-zinc-400 text-center py-8">{t("review.empty")}</div>
      )}

      <RejectModal
        key={rejectTarget?.id ?? "closed"}
        open={rejectTarget !== null}
        onClose={() => setRejectTarget(null)}
        onSubmit={submitReject}
        busy={busy}
        t={t}
      />
    </>
  );
}
