"use client";

import { useState, useCallback } from "react";
import PageHeader from "../components/page-header";
import StatusBadge from "../components/status-badge";
import SpreadsheetGrid, { type GridColumn, type GridRow } from "../components/spreadsheet-grid";
import { useMismatches } from "../lib/swr";
import { useOrgPeriod } from "../lib/period";
import { RippleButton } from "@/components/ui/multi-type-ripple-buttons";
import { CARD } from "@/app/lib/ui";
import { useT, type TFunction } from "@/app/lib/i18n";

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

type FilterType = "all" | "missing_from_erp" | "missing_from_statement" | "quantity" | "price" | "resolved";
type ViewMode = "review" | "spreadsheet";

function formatNum(n: number | null | undefined, decimals = 2): string {
  if (n == null) return "-";
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCurrency(n: number | null | undefined): string {
  if (n == null) return "-";
  return `¥${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function DiscrepancyLabel({ type }: { type: string | null }) {
  const t = useT();
  if (!type) return <span className="text-zinc-300">-</span>;

  const labels: Record<string, { text: string; color: string; explanation: string }> = {
    missing_from_erp: {
      text: t("mismatches.disc_missing_from_erp"),
      color: "text-red-600 bg-red-50 border border-red-200",
      explanation: t("mismatches.disc_missing_from_erp_explain"),
    },
    missing_from_statement: {
      text: t("mismatches.disc_missing_from_statement"),
      color: "text-amber-600 bg-amber-50 border border-amber-200",
      explanation: t("mismatches.disc_missing_from_statement_explain"),
    },
    quantity_over: {
      text: t("mismatches.disc_qty_over"),
      color: "text-orange-600 bg-orange-50 border border-orange-200",
      explanation: t("mismatches.disc_qty_over_explain"),
    },
    quantity_under: {
      text: t("mismatches.disc_qty_under"),
      color: "text-orange-600 bg-orange-50 border border-orange-200",
      explanation: t("mismatches.disc_qty_under_explain"),
    },
    price_higher: {
      text: t("mismatches.disc_price_higher"),
      color: "text-purple-600 bg-purple-50 border border-purple-200",
      explanation: t("mismatches.disc_price_higher_explain"),
    },
    price_lower: {
      text: t("mismatches.disc_price_lower"),
      color: "text-purple-600 bg-purple-50 border border-purple-200",
      explanation: t("mismatches.disc_price_lower_explain"),
    },
    amount_mismatch: {
      text: t("mismatches.disc_amount_mismatch"),
      color: "text-blue-600 bg-blue-50 border border-blue-200",
      explanation: t("mismatches.disc_amount_mismatch_explain"),
    },
  };

  const parts = type.split(",");
  return (
    <div className="flex flex-wrap gap-1">
      {parts.map((p) => {
        const l = labels[p.trim()] || {
          text: p.trim(),
          color: "text-zinc-600 bg-zinc-50 border border-zinc-200",
          explanation: "",
        };
        return (
          <span
            key={p}
            className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium ${l.color}`}
            title={l.explanation}
          >
            {l.text}
          </span>
        );
      })}
    </div>
  );
}

function MatchExplanation({ supplier }: { supplier: SupplierMismatch }) {
  const t = useT();
  const s = supplier;
  const matchedCount = s.total_statement - s.unmatched_stmt;
  const matchPct = s.match_rate ?? 0;

  return (
    <div className="px-4 py-3 bg-zinc-50 border-t border-border text-xs text-zinc-600 space-y-2">
      <div className="font-medium text-zinc-700 text-sm">{t("mismatches.match_summary")}</div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="text-zinc-400 mb-0.5">{t("mismatches.statement_items_matched")}</div>
          <div className="font-mono text-sm">
            <span className="font-semibold text-green-600">{matchedCount}</span>
            <span className="text-zinc-400"> / {s.total_statement}</span>
            <span className={`ml-1 font-semibold ${matchPct >= 90 ? "text-green-600" : matchPct >= 70 ? "text-amber-600" : "text-red-500"}`}>
              ({matchPct.toFixed(1)}%)
            </span>
          </div>
        </div>
        <div>
          <div className="text-zinc-400 mb-0.5">{t("mismatches.erp_records_for_period")}</div>
          <div className="font-mono text-sm">{s.total_erp}</div>
        </div>
        <div>
          <div className="text-zinc-400 mb-0.5">{t("mismatches.total_issues_to_review")}</div>
          <div className="font-mono text-sm font-semibold text-red-500">{s.total_mismatches}</div>
        </div>
      </div>

      <div className="space-y-1.5 pt-1">
        {s.unmatched_stmt > 0 && (
          <div className="flex items-start gap-2 bg-red-50 rounded px-2.5 py-1.5 border border-red-100">
            <span className="font-semibold text-red-600 shrink-0">{s.unmatched_stmt}</span>
            <span>
              <span className="font-medium text-red-700">{t("mismatches.unmatched_stmt_label")}</span>
              {" "}{t("mismatches.unmatched_stmt_detail")}
            </span>
          </div>
        )}
        {s.unmatched_erp > 0 && (
          <div className="flex items-start gap-2 bg-amber-50 rounded px-2.5 py-1.5 border border-amber-100">
            <span className="font-semibold text-amber-600 shrink-0">{s.unmatched_erp}</span>
            <span>
              <span className="font-medium text-amber-700">{t("mismatches.unmatched_erp_label")}</span>
              {" "}{t("mismatches.unmatched_erp_detail")}
            </span>
          </div>
        )}
        {s.qty_issues > 0 && (
          <div className="flex items-start gap-2 bg-orange-50 rounded px-2.5 py-1.5 border border-orange-100">
            <span className="font-semibold text-orange-600 shrink-0">{s.qty_issues}</span>
            <span>
              <span className="font-medium text-orange-700">{t("mismatches.qty_issues_label")}</span>
              {" "}{t("mismatches.qty_issues_detail")}
            </span>
          </div>
        )}
        {s.price_issues > 0 && (
          <div className="flex items-start gap-2 bg-purple-50 rounded px-2.5 py-1.5 border border-purple-100">
            <span className="font-semibold text-purple-600 shrink-0">{s.price_issues}</span>
            <span>
              <span className="font-medium text-purple-700">{t("mismatches.price_issues_label")}</span>
              {" "}{t("mismatches.price_issues_detail")}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function ResolveModal({
  items,
  onClose,
  onResolved,
}: {
  items: MismatchItem[];
  onClose: () => void;
  onResolved: (resolvedIds: string[]) => void;
}) {
  const t = useT();
  const [note, setNote] = useState("");
  const [resolvedBy, setResolvedBy] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleResolve() {
    if (!note.trim()) return;
    setSubmitting(true);

    try {
      if (items.length === 1) {
        const res = await fetch(`/api/v1/reconciliation/results/${items[0].id}/resolve`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resolution_note: note,
            resolved_by: resolvedBy || undefined,
          }),
        });
        if (res.ok) {
          onResolved([items[0].id]);
        }
      } else {
        const res = await fetch("/api/v1/reconciliation/results/bulk-resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            result_ids: items.map((i) => i.id),
            resolution_note: note,
            resolved_by: resolvedBy || undefined,
          }),
        });
        if (res.ok) {
          onResolved(items.map((i) => i.id));
        }
      }
    } catch {
      // ignore
    }
    setSubmitting(false);
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-card rounded-2xl shadow-xl w-full max-w-md p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold text-sm mb-3">
          {items.length === 1
            ? t("mismatches.resolve_item")
            : t("mismatches.resolve_n_items", { n: items.length })}
        </h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">{t("mismatches.resolution_note")}</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("mismatches.resolution_note_placeholder")}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">{t("mismatches.resolved_by")}</label>
            <input
              type="text"
              value={resolvedBy}
              onChange={(e) => setResolvedBy(e.target.value)}
              placeholder={t("mismatches.resolved_by_placeholder")}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            />
          </div>
        </div>
        <div className="flex gap-2 mt-4 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
          >
            {t("common.cancel")}
          </button>
          <RippleButton
            variant="hover"
            hoverRippleColor="#16A34A"
            onClick={handleResolve}
            disabled={!note.trim() || submitting}
            className="!px-3 !py-1.5 !text-xs !rounded-lg text-green-700 font-medium"
          >
            <span className="flex items-center gap-1.5">
              <span aria-hidden>✓</span>
              {submitting ? t("mismatches.resolving") : t("mismatches.mark_as_resolved")}
            </span>
          </RippleButton>
        </div>
      </div>
    </div>
  );
}

function SupplierCard({
  supplier,
  expanded,
  onToggle,
  onItemsResolved,
}: {
  supplier: SupplierMismatch;
  expanded: boolean;
  onToggle: () => void;
  onItemsResolved: (resolvedIds: string[]) => void;
}) {
  const t = useT();
  const s = supplier;
  const [filter, setFilter] = useState<FilterType>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [resolveItems, setResolveItems] = useState<MismatchItem[] | null>(null);

  const matchColor =
    s.match_rate == null
      ? "text-zinc-400"
      : s.match_rate >= 90
        ? "text-green-600"
        : s.match_rate >= 70
          ? "text-amber-600"
          : "text-red-500";

  const filteredItems = s.items.filter((item) => {
    if (filter === "all") return true;
    if (filter === "resolved") return item.status === "resolved";
    if (filter === "missing_from_erp") return item.discrepancy_type === "missing_from_erp";
    if (filter === "missing_from_statement") return item.discrepancy_type === "missing_from_statement";
    if (filter === "quantity") return item.discrepancy_type?.includes("quantity");
    if (filter === "price") return item.discrepancy_type?.includes("price");
    return true;
  });

  const unresolvedItems = filteredItems.filter((i) => i.status !== "resolved");
  const resolvedCount = s.items.filter((i) => i.status === "resolved").length;

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllUnresolved() {
    setSelected(new Set(unresolvedItems.map((i) => i.id)));
  }

  return (
    <div className={`${CARD} overflow-hidden`}>
      {/* Header */}
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center gap-4 bg-muted hover:bg-zinc-100 transition-colors text-left"
      >
        <svg
          className={`w-4 h-4 text-zinc-400 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>

        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm truncate">{s.supplier_name}</div>
          <div className="text-xs text-zinc-400">{s.vendor_code}</div>
        </div>

        <div className="flex gap-6 items-center text-xs shrink-0">
          <div className="text-center">
            <div className="text-zinc-400">{t("mismatches.match_rate")}</div>
            <div className={`font-semibold text-sm ${matchColor}`}>
              {s.match_rate != null ? `${s.match_rate.toFixed(1)}%` : "-"}
            </div>
          </div>
          <div className="text-center">
            <div className="text-zinc-400">{t("mismatches.issues")}</div>
            <div className="font-semibold text-sm">
              <span className="text-red-500">{s.total_mismatches - resolvedCount}</span>
              {resolvedCount > 0 && (
                <span className="text-green-500 ml-1">({t("mismatches.n_resolved", { n: resolvedCount })})</span>
              )}
            </div>
          </div>
          <div className="text-center">
            <div className="text-zinc-400">{t("mismatches.erp_stmt")}</div>
            <div className="font-mono text-sm">{s.total_erp} / {s.total_statement}</div>
          </div>
        </div>

        <div className="flex gap-1.5 shrink-0">
          {s.unmatched_stmt > 0 && (
            <span className="px-2 py-0.5 rounded text-xs bg-red-50 text-red-600 border border-red-200">
              {t("mismatches.badge_not_in_erp", { n: s.unmatched_stmt })}
            </span>
          )}
          {s.unmatched_erp > 0 && (
            <span className="px-2 py-0.5 rounded text-xs bg-amber-50 text-amber-600 border border-amber-200">
              {t("mismatches.badge_not_in_stmt", { n: s.unmatched_erp })}
            </span>
          )}
          {s.qty_issues > 0 && (
            <span className="px-2 py-0.5 rounded text-xs bg-orange-50 text-orange-600 border border-orange-200">
              {t("mismatches.badge_qty", { n: s.qty_issues })}
            </span>
          )}
          {s.price_issues > 0 && (
            <span className="px-2 py-0.5 rounded text-xs bg-purple-50 text-purple-600 border border-purple-200">
              {t("mismatches.badge_price", { n: s.price_issues })}
            </span>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {expanded && (
        <>
          <MatchExplanation supplier={s} />

          {/* Filter tabs + bulk actions */}
          <div className="px-4 py-2 border-t border-border flex items-center justify-between bg-card">
            <div className="flex gap-1">
              {([
                ["all", `${t("mismatches.filter_all")} (${s.items.length})`],
                ["missing_from_erp", `${t("mismatches.filter_not_in_erp")} (${s.unmatched_stmt})`],
                ["missing_from_statement", `${t("mismatches.filter_not_in_stmt")} (${s.unmatched_erp})`],
                ["quantity", `${t("mismatches.filter_qty")} (${s.qty_issues})`],
                ["price", `${t("mismatches.filter_price")} (${s.price_issues})`],
                ["resolved", `${t("mismatches.filter_resolved")} (${resolvedCount})`],
              ] as [FilterType, string][])
                .filter(([key]) => {
                  if (key === "all") return true;
                  if (key === "missing_from_erp") return s.unmatched_stmt > 0;
                  if (key === "missing_from_statement") return s.unmatched_erp > 0;
                  if (key === "quantity") return s.qty_issues > 0;
                  if (key === "price") return s.price_issues > 0;
                  if (key === "resolved") return resolvedCount > 0;
                  return true;
                })
                .map(([key, label]) => (
                  <button
                    key={key}
                    onClick={(e) => { e.stopPropagation(); setFilter(key); setSelected(new Set()); }}
                    className={`px-2.5 py-1 text-xs rounded-lg transition-colors ${
                      filter === key
                        ? "bg-accent text-white"
                        : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                    }`}
                  >
                    {label}
                  </button>
                ))}
            </div>

            <div className="flex gap-2">
              {selected.size > 0 && (
                <button
                  onClick={() => {
                    const items = filteredItems.filter((i) => selected.has(i.id));
                    setResolveItems(items);
                  }}
                  className="px-3 py-1 text-xs bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                >
                  {t("mismatches.resolve_n_selected", { n: selected.size })}
                </button>
              )}
              {unresolvedItems.length > 0 && selected.size === 0 && (
                <button
                  onClick={selectAllUnresolved}
                  className="px-2.5 py-1 text-xs text-zinc-500 hover:text-zinc-700"
                >
                  {t("mismatches.select_all_unresolved")}
                </button>
              )}
              {selected.size > 0 && (
                <button
                  onClick={() => setSelected(new Set())}
                  className="px-2.5 py-1 text-xs text-zinc-500 hover:text-zinc-700"
                >
                  {t("mismatches.clear")}
                </button>
              )}
            </div>
          </div>

          {/* Items table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-t border-b border-border bg-zinc-50 text-zinc-500">
                  <th className="text-center px-2 py-2 w-8">
                    <input
                      type="checkbox"
                      checked={selected.size > 0 && selected.size === unresolvedItems.length}
                      onChange={() => {
                        if (selected.size === unresolvedItems.length) setSelected(new Set());
                        else selectAllUnresolved();
                      }}
                      className="rounded"
                    />
                  </th>
                  <th className="text-left px-3 py-2 font-medium">{t("mismatches.col_issue")}</th>
                  <th className="text-left px-3 py-2 font-medium">{t("mismatches.col_po")}</th>
                  <th className="text-left px-3 py-2 font-medium">{t("mismatches.col_part_number")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_erp_qty")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_stmt_qty")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_qty_delta")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_erp_amt")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_stmt_amt")}</th>
                  <th className="text-right px-3 py-2 font-medium">{t("mismatches.col_amt_delta")}</th>
                  <th className="text-center px-3 py-2 font-medium">{t("common.status")}</th>
                  <th className="text-center px-3 py-2 font-medium w-20">{t("common.action")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => {
                  const po = item.erp?.po_number || item.statement?.po_number || "-";
                  const pn = item.erp?.material_number || item.statement?.material_number || "-";
                  const isUnmatched = item.match_type === "unmatched";
                  const isResolved = item.status === "resolved";
                  const rowBg = isResolved
                    ? "bg-green-50/30"
                    : isUnmatched
                      ? "bg-red-50/30"
                      : "";

                  return (
                    <tr
                      key={item.id}
                      className={`border-t border-border hover:bg-zinc-50 ${rowBg}`}
                    >
                      <td className="text-center px-2 py-2">
                        {!isResolved && (
                          <input
                            type="checkbox"
                            checked={selected.has(item.id)}
                            onChange={() => toggleSelect(item.id)}
                            className="rounded"
                          />
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <DiscrepancyLabel type={item.discrepancy_type} />
                      </td>
                      <td className="px-3 py-2 font-mono whitespace-nowrap">{po}</td>
                      <td
                        className="px-3 py-2 font-mono whitespace-nowrap text-zinc-600 max-w-[180px] truncate"
                        title={pn}
                      >
                        {pn}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.erp ? formatNum(item.erp.quantity, 0) : <span className="text-red-300">-</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.statement ? formatNum(item.statement.quantity, 0) : <span className="text-amber-300">-</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.quantity_delta != null ? (
                          <span className={item.quantity_delta !== 0 ? "text-orange-600 font-medium" : ""}>
                            {item.quantity_delta > 0 ? "+" : ""}{formatNum(item.quantity_delta, 0)}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.erp ? formatCurrency(item.erp.amount) : <span className="text-red-300">-</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.statement ? formatCurrency(item.statement.amount) : <span className="text-amber-300">-</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {item.amount_delta != null ? (
                          <span className={item.amount_delta !== 0 ? "text-red-600 font-medium" : ""}>
                            {item.amount_delta > 0 ? "+" : ""}{formatCurrency(item.amount_delta)}
                          </span>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {isResolved ? (
                          <span
                            className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 cursor-help"
                            title={item.resolution_note || ""}
                          >
                            {t("mismatches.resolved")}
                          </span>
                        ) : (
                          <StatusBadge status={item.status} />
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {!isResolved && (
                          <button
                            onClick={() => setResolveItems([item])}
                            className="px-2 py-0.5 text-xs text-green-600 hover:text-green-800 hover:bg-green-50 rounded-lg transition-colors"
                          >
                            {t("common.resolve")}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {filteredItems.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-zinc-400">
              {t("mismatches.no_items_match_filter")}
            </div>
          )}
        </>
      )}

      {resolveItems && (
        <ResolveModal
          items={resolveItems}
          onClose={() => setResolveItems(null)}
          onResolved={(ids) => {
            onItemsResolved(ids);
            setSelected(new Set());
          }}
        />
      )}
    </div>
  );
}

// ── Spreadsheet View helpers ──

function buildSpreadsheetColumns(t: TFunction): GridColumn[] {
  return [
    { key: "flag", label: t("mismatches.col_flag"), width: 100, editable: true, type: "select", align: "center", options: [
      { value: "", label: "-" },
      { value: "flagged", label: t("mismatches.flag_flagged"), color: "#dc2626" },
      { value: "approved", label: t("mismatches.flag_approved"), color: "#16a34a" },
      { value: "query", label: t("mismatches.flag_query"), color: "#d97706" },
    ]},
    { key: "discrepancy", label: t("mismatches.col_issue"), width: 130 },
    { key: "po_number", label: t("mismatches.col_po_number"), width: 120 },
    { key: "part_number", label: t("mismatches.col_part_number"), width: 150 },
    { key: "erp_qty", label: t("mismatches.col_erp_qty"), width: 80, editable: true, type: "number", align: "right" },
    { key: "stmt_qty", label: t("mismatches.col_stmt_qty"), width: 80, editable: true, type: "number", align: "right" },
    { key: "qty_delta", label: t("mismatches.col_qty_delta"), width: 80, align: "right" },
    { key: "erp_price", label: t("mismatches.col_erp_price"), width: 90, editable: true, type: "number", align: "right" },
    { key: "stmt_price", label: t("mismatches.col_stmt_price"), width: 90, editable: true, type: "number", align: "right" },
    { key: "price_delta", label: t("mismatches.col_price_delta"), width: 90, align: "right" },
    { key: "erp_amount", label: t("mismatches.col_erp_amount"), width: 100, editable: true, type: "number", align: "right" },
    { key: "stmt_amount", label: t("mismatches.col_stmt_amount"), width: 100, editable: true, type: "number", align: "right" },
    { key: "amt_delta", label: t("mismatches.col_amt_delta"), width: 100, align: "right" },
    { key: "status", label: t("common.status"), width: 90, align: "center" },
    { key: "notes", label: t("mismatches.col_notes"), width: 200, editable: true, type: "text" },
  ];
}

function supplierToRows(supplier: SupplierMismatch): GridRow[] {
  return supplier.items.map((item) => ({
    id: item.id,
    flag: "",
    discrepancy: item.discrepancy_type ?? "",
    po_number: item.erp?.po_number || item.statement?.po_number || "",
    part_number: item.erp?.material_number || item.statement?.material_number || "",
    erp_qty: item.erp?.quantity ?? null,
    stmt_qty: item.statement?.quantity ?? null,
    qty_delta: item.quantity_delta,
    erp_price: item.erp?.po_price ?? item.erp?.unit_price ?? null,
    stmt_price: item.statement?.unit_price ?? null,
    price_delta: item.price_delta,
    erp_amount: item.erp?.amount ?? null,
    stmt_amount: item.statement?.amount ?? null,
    amt_delta: item.amount_delta,
    status: item.status,
    notes: item.resolution_note ?? "",
  }));
}

function recomputeDeltas(
  row: GridRow,
  edits: Record<string, unknown>
): Record<string, unknown> {
  const get = (key: string) => edits[key] ?? row[key];
  const erpQty = Number(get("erp_qty")) || 0;
  const stmtQty = Number(get("stmt_qty")) || 0;
  const erpAmt = Number(get("erp_amount")) || 0;
  const stmtAmt = Number(get("stmt_amount")) || 0;
  const erpPrice = Number(get("erp_price")) || 0;
  const stmtPrice = Number(get("stmt_price")) || 0;

  const out: Record<string, unknown> = {};
  if (edits["erp_qty"] !== undefined || edits["stmt_qty"] !== undefined) {
    out["qty_delta"] = stmtQty - erpQty;
  }
  if (edits["erp_amount"] !== undefined || edits["stmt_amount"] !== undefined) {
    out["amt_delta"] = stmtAmt - erpAmt;
  }
  if (edits["erp_price"] !== undefined || edits["stmt_price"] !== undefined) {
    out["price_delta"] = stmtPrice - erpPrice;
  }
  return out;
}

function exportCSV(
  columns: GridColumn[],
  rows: GridRow[],
  edits: Record<string, Record<string, unknown>>,
  supplierName?: string
) {
  const header = columns.map((c) => c.label).join(",");
  const lines = rows.map((row) => {
    return columns
      .map((col) => {
        const val = edits[row.id]?.[col.key] ?? row[col.key];
        const str = val == null ? "" : String(val);
        return str.includes(",") || str.includes('"') || str.includes("\n")
          ? `"${str.replace(/"/g, '""')}"`
          : str;
      })
      .join(",");
  });
  const csv = [header, ...lines].join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const slug = supplierName?.replace(/[^a-zA-Z0-9\u4e00-\u9fff]+/g, "-") ?? "all";
  a.download = `mismatches-${slug}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function SpreadsheetView({
  data,
}: {
  data: SupplierMismatch[];
}) {
  const t = useT();
  const SPREADSHEET_COLUMNS = buildSpreadsheetColumns(t);
  const [selectedSupplierId, setSelectedSupplierId] = useState(data[0]?.supplier_id ?? "");
  const [editsMap, setEditsMap] = useState<Record<string, Record<string, Record<string, unknown>>>>({});

  const selectedSupplier = data.find((s) => s.supplier_id === selectedSupplierId);
  const rows = selectedSupplier ? supplierToRows(selectedSupplier) : [];
  const edits = editsMap[selectedSupplierId] ?? {};

  const editCount = Object.values(edits).reduce(
    (acc, e) => acc + Object.keys(e).length,
    0
  );
  const totalEdits = Object.values(editsMap).reduce(
    (acc, supplierEdits) =>
      acc + Object.values(supplierEdits).reduce((a, e) => a + Object.keys(e).length, 0),
    0
  );

  const handleCellChange = useCallback(
    (rowId: string, colKey: string, value: unknown) => {
      setEditsMap((prev) => {
        const supplierEdits = { ...prev[selectedSupplierId] };
        const rowEdits = { ...supplierEdits[rowId], [colKey]: value };
        const row = rows.find((r) => r.id === rowId);
        if (row) {
          const deltas = recomputeDeltas(row, rowEdits);
          Object.assign(rowEdits, deltas);
        }
        supplierEdits[rowId] = rowEdits;
        return { ...prev, [selectedSupplierId]: supplierEdits };
      });
    },
    [rows, selectedSupplierId]
  );

  const matchColor = (rate: number | null) =>
    rate == null ? "text-zinc-400" : rate >= 90 ? "text-green-600" : rate >= 70 ? "text-amber-600" : "text-red-500";

  return (
    <div className="space-y-3">
      {/* Supplier tabs */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        {data.map((s) => {
          const isSelected = s.supplier_id === selectedSupplierId;
          const hasEdits = Object.keys(editsMap[s.supplier_id] ?? {}).length > 0;
          return (
            <button
              key={s.supplier_id}
              onClick={() => setSelectedSupplierId(s.supplier_id)}
              className={`shrink-0 px-3.5 py-2 rounded-lg text-xs font-medium transition-colors border ${
                isSelected
                  ? "bg-accent text-white border-accent"
                  : "bg-card text-zinc-600 border-border hover:bg-muted"
              }`}
            >
              <span>{s.supplier_name}</span>
              <span className={`ml-2 font-mono ${isSelected ? "text-white/70" : matchColor(s.match_rate)}`}>
                {s.match_rate != null ? `${s.match_rate.toFixed(0)}%` : "-"}
              </span>
              <span className={`ml-1.5 ${isSelected ? "text-white/70" : "text-red-400"}`}>
                ({s.total_mismatches})
              </span>
              {hasEdits && (
                <span className={`ml-1 w-1.5 h-1.5 rounded-full inline-block ${isSelected ? "bg-white/60" : "bg-accent"}`} />
              )}
            </button>
          );
        })}
      </div>

      {/* Supplier summary */}
      {selectedSupplier && (
        <div className="flex items-center gap-4 text-xs text-zinc-500">
          <span className="font-medium text-zinc-700">{selectedSupplier.supplier_name}</span>
          <span className="text-zinc-300">|</span>
          <span>{selectedSupplier.vendor_code}</span>
          <span className="text-zinc-300">|</span>
          <span>{t("mismatches.erp_label")} <span className="font-mono">{selectedSupplier.total_erp}</span></span>
          <span>{t("mismatches.stmt_label")} <span className="font-mono">{selectedSupplier.total_statement}</span></span>
          <span className="text-zinc-300">|</span>
          <span className={matchColor(selectedSupplier.match_rate)}>
            {t("mismatches.match_rate_label")} <span className="font-semibold">{selectedSupplier.match_rate?.toFixed(1) ?? "-"}%</span>
          </span>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <span>{t("mismatches.n_rows", { n: rows.length })}</span>
          {editCount > 0 && (
            <span className="text-accent font-medium">{t("mismatches.n_edits", { n: editCount })}</span>
          )}
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-green-50 border border-green-200" />
            {t("mismatches.edited_cells")}
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-accent text-[9px]">*</span>
            {t("mismatches.editable_column")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {totalEdits > 0 && (
            <button
              onClick={() => setEditsMap({})}
              className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted transition-colors text-zinc-600"
            >
              {t("mismatches.reset_all_edits")}
            </button>
          )}
          {editCount > 0 && (
            <button
              onClick={() => setEditsMap((prev) => {
                const next = { ...prev };
                delete next[selectedSupplierId];
                return next;
              })}
              className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted transition-colors text-zinc-600"
            >
              {t("mismatches.reset_this_supplier")}
            </button>
          )}
          <button
            onClick={() => exportCSV(
              SPREADSHEET_COLUMNS,
              rows,
              edits,
              selectedSupplier?.supplier_name
            )}
            className="px-3 py-1.5 text-xs bg-accent text-white rounded-lg hover:bg-accent-dark transition-colors flex items-center gap-1.5"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            {t("mismatches.export_csv")}
          </button>
        </div>
      </div>

      <SpreadsheetGrid
        columns={SPREADSHEET_COLUMNS}
        rows={rows}
        edits={edits}
        onCellChange={handleCellChange}
      />
    </div>
  );
}

// ── Main page ──

export default function MismatchesPage() {
  const t = useT();
  const { orgId, period } = useOrgPeriod();
  const { data, mismatchesLoading: loading, mismatchesError, refreshMismatches } = useMismatches(orgId, period);
  const error = mismatchesError?.message ?? "";
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>("review");

  function toggleExpand(supplierId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(supplierId)) next.delete(supplierId);
      else next.add(supplierId);
      return next;
    });
  }

  function expandAll() {
    setExpanded(new Set(data.map((d) => d.supplier_id)));
  }

  function collapseAll() {
    setExpanded(new Set());
  }

  function handleItemsResolved(resolvedIds: string[]) {
    refreshMismatches();
  }

  const totalMismatches = data.reduce((acc, d) => acc + d.total_mismatches, 0);
  const totalResolved = data.reduce(
    (acc, d) => acc + d.items.filter((i) => i.status === "resolved").length,
    0
  );
  const suppliersWithIssues = data.filter((d) => d.total_mismatches > 0).length;

  return (
    <>
      <PageHeader
        title={t("mismatches.title")}
        description={t("mismatches.description")}
      />

      {/* Controls */}
      <div className="flex gap-4 items-end mb-6">
        {/* View mode toggle */}
        {!loading && data.length > 0 && (
          <div className="ml-auto flex rounded-lg border border-border overflow-hidden">
            <button
              onClick={() => setViewMode("review")}
              className={`px-3 py-2 text-xs font-medium transition-colors flex items-center gap-1.5 ${
                viewMode === "review"
                  ? "bg-accent text-white"
                  : "bg-card text-zinc-600 hover:bg-muted"
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
              {t("common.review")}
            </button>
            <button
              onClick={() => setViewMode("spreadsheet")}
              className={`px-3 py-2 text-xs font-medium transition-colors flex items-center gap-1.5 border-l border-border ${
                viewMode === "spreadsheet"
                  ? "bg-accent text-white"
                  : "bg-card text-zinc-600 hover:bg-muted"
              }`}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <line x1="3" y1="9" x2="21" y2="9" />
                <line x1="3" y1="15" x2="21" y2="15" />
                <line x1="9" y1="3" x2="9" y2="21" />
                <line x1="15" y1="3" x2="15" y2="21" />
              </svg>
              {t("mismatches.spreadsheet")}
            </button>
          </div>
        )}
      </div>

      {/* Summary bar */}
      {!loading && data.length > 0 && (
        <div className="flex items-center justify-between mb-4">
          <div className="flex gap-4 text-sm">
            <span>
              <span className="font-semibold">{suppliersWithIssues}</span>
              <span className="text-zinc-500"> {t("mismatches.suppliers_with_mismatches")}</span>
            </span>
            <span className="text-zinc-300">|</span>
            <span>
              <span className="font-semibold text-red-500">{totalMismatches - totalResolved}</span>
              <span className="text-zinc-500"> {t("mismatches.unresolved")}</span>
            </span>
            {totalResolved > 0 && (
              <>
                <span className="text-zinc-300">|</span>
                <span>
                  <span className="font-semibold text-green-500">{totalResolved}</span>
                  <span className="text-zinc-500"> {t("mismatches.resolved")}</span>
                </span>
              </>
            )}
          </div>
          {viewMode === "review" && (
            <div className="flex gap-2">
              <button
                onClick={expandAll}
                className="px-3 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
              >
                {t("mismatches.expand_all")}
              </button>
              <button
                onClick={collapseAll}
                className="px-3 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
              >
                {t("mismatches.collapse_all")}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="text-sm text-zinc-400 py-8 text-center">{t("mismatches.loading_mismatches")}</div>
      ) : error ? (
        <div className="text-sm text-red-600 bg-red-50 p-3 rounded-lg">{error}</div>
      ) : data.length === 0 ? (
        <div className="text-sm text-zinc-400 py-8 text-center border border-dashed border-border rounded-2xl">
          {t("mismatches.no_mismatches_found")}
        </div>
      ) : viewMode === "spreadsheet" ? (
        <SpreadsheetView data={data} />
      ) : (
        <div className="space-y-3">
          {data.map((supplier) => (
            <SupplierCard
              key={supplier.supplier_id}
              supplier={supplier}
              expanded={expanded.has(supplier.supplier_id)}
              onToggle={() => toggleExpand(supplier.supplier_id)}
              onItemsResolved={handleItemsResolved}
            />
          ))}
        </div>
      )}
    </>
  );
}
