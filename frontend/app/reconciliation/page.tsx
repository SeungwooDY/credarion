"use client";

import { useEffect, useState, useRef } from "react";
import PageHeader from "../components/page-header";
import StatusBadge from "../components/status-badge";
import { useOrgs, useSuppliers } from "../lib/swr";

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

interface ResultRow {
  id: string;
  match_type: string;
  status: string;
  discrepancy_type: string | null;
  quantity_delta: number | null;
  price_delta: number | null;
  confidence: number | null;
}

const PROGRESS_PHRASES = [
  "Loading ERP records and statement data...",
  "Normalizing PO numbers and part numbers...",
  "Layer 1: Exact matching on PO + part number...",
  "Layer 2: Fuzzy matching on similar POs...",
  "Layer 3: Aggregate matching for consolidated deliveries...",
  "Layer 4: AI-powered matching for remaining items...",
  "Classifying discrepancies...",
  "Calculating match rate...",
  "Finalizing results...",
];

function ThinkingIndicator({ supplierName }: { supplierName: string }) {
  const [phraseIndex, setPhraseIndex] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    timerRef.current = setInterval(() => {
      setPhraseIndex((prev) =>
        prev < PROGRESS_PHRASES.length - 1 ? prev + 1 : prev
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
            Reconciling {supplierName}
          </span>
          <div className="thinking-dots ml-auto flex gap-1">
            <span /><span /><span />
          </div>
        </div>

        <div className="space-y-1.5 pl-10">
          {PROGRESS_PHRASES.slice(0, phraseIndex + 1).map((phrase, i) => (
            <div
              key={i}
              className={`text-sm animate-fade-in-up ${
                i === phraseIndex
                  ? "text-accent font-medium"
                  : "text-zinc-400"
              }`}
            >
              {i < phraseIndex && (
                <svg className="inline w-3.5 h-3.5 mr-1.5 text-green-500 -mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
              {i === phraseIndex && (
                <span className="inline-block w-3.5 mr-1.5" />
              )}
              {phrase}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ReconciliationPage() {
  const { orgs } = useOrgs();
  const [orgId, setOrgId] = useState("");
  const [period, setPeriod] = useState("2026-03");
  const { suppliers, suppliersLoading, refreshSuppliers } = useSuppliers(orgId, period);

  const [supplierId, setSupplierId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [results, setResults] = useState<ResultRow[]>([]);

  useEffect(() => {
    if (orgs.length > 0 && !orgId) setOrgId(orgs[0].id);
  }, [orgs, orgId]);

  async function runReconciliation(sid?: string) {
    const targetId = sid || supplierId;
    if (!targetId || !period) return;
    setLoading(true);
    setError("");
    setRunResult(null);
    setResults([]);
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

      const resResults = await fetch(
        `/api/v1/reconciliation/results?run_id=${data.run.id}&limit=100`
      );
      if (resResults.ok) {
        setResults(await resResults.json());
      }

      refreshSuppliers();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setLoading(false);
  }

  const run = runResult?.run;
  const selectedSupplier = suppliers.find((s) => s.id === supplierId);
  const readyCount = suppliers.filter((s) => s.ready).length;
  const notReadyCount = suppliers.filter((s) => !s.ready).length;

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Run the 4-layer matching engine against suppliers with uploaded statements"
      />

      {/* Controls */}
      <div className="flex gap-4 items-end mb-6">
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1.5">
            Organization
          </label>
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            className="border border-border rounded-lg px-3 py-2 text-sm bg-card focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1.5">Period</label>
          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="border border-border rounded-lg px-3 py-2 text-sm bg-card w-28 focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
          />
        </div>
      </div>

      {/* Supplier readiness table */}
      <div className="bg-card rounded-2xl shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden mb-6">
        <div className="bg-muted px-4 py-3 flex items-center justify-between border-b border-border">
          <h3 className="text-sm font-semibold text-zinc-700">
            Suppliers for {period}
          </h3>
          {!suppliersLoading && (
            <div className="text-xs text-zinc-500">
              <span className="font-medium text-accent">{readyCount} ready</span>
              {notReadyCount > 0 && (
                <span className="ml-2 text-zinc-400">
                  {notReadyCount} missing data
                </span>
              )}
            </div>
          )}
        </div>

        {suppliersLoading ? (
          <div className="p-6 text-sm text-zinc-400 text-center">Loading suppliers...</div>
        ) : suppliers.length === 0 ? (
          <div className="p-6 text-sm text-zinc-400 text-center">
            No suppliers with data for this period. Upload GRN and statements first.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-zinc-400 uppercase tracking-wider">
                <th className="text-left px-4 py-2.5 font-medium">Supplier</th>
                <th className="text-right px-4 py-2.5 font-medium">ERP</th>
                <th className="text-right px-4 py-2.5 font-medium">Statement</th>
                <th className="text-center px-4 py-2.5 font-medium">Status</th>
                <th className="text-right px-4 py-2.5 font-medium">Match Rate</th>
                <th className="text-center px-4 py-2.5 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr
                  key={s.id}
                  className={`border-t border-border transition-colors ${
                    s.id === supplierId
                      ? "bg-accent-light"
                      : "hover:bg-muted"
                  } ${!s.ready ? "opacity-50" : ""}`}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-800">{s.name}</div>
                    <div className="text-xs text-zinc-400 mt-0.5">{s.vendor_code}</div>
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-zinc-600">
                    {s.erp_count > 0 ? (
                      s.erp_count
                    ) : (
                      <span className="text-red-400">0</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-zinc-600">
                    {s.statement_rows > 0 ? (
                      s.statement_rows
                    ) : (
                      <span className="text-red-400 text-xs font-sans">
                        Missing
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {s.ready ? (
                      <span className="inline-block text-xs px-2.5 py-0.5 rounded-full font-medium bg-accent-light text-accent">
                        Ready
                      </span>
                    ) : (
                      <span className="inline-block text-xs px-2.5 py-0.5 rounded-full bg-zinc-100 text-zinc-500">
                        {!s.has_statement ? "No statement" : "No ERP"}
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
                      onClick={() => runReconciliation(s.id)}
                      disabled={!s.ready || loading}
                      className="px-3.5 py-1.5 text-xs font-medium text-white rounded-lg bg-accent hover:bg-accent-dark disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                    >
                      {loading && supplierId === s.id ? "Running..." : "Run"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Thinking indicator while running */}
      {loading && (
        <ThinkingIndicator supplierName={selectedSupplier?.name || "supplier"} />
      )}

      {error && (
        <div className="text-sm text-red-600 bg-red-50 border border-red-200 p-3 rounded-lg mb-4">
          {error}
        </div>
      )}

      {/* Summary stats */}
      {run && !loading && (
        <>
          <h3 className="text-sm font-semibold mb-3 text-zinc-700">
            Results: {selectedSupplier?.name || ""}
          </h3>
          <div className="grid grid-cols-6 gap-3 mb-6">
            {[
              { label: "Status", val: run.status, badge: true },
              { label: "ERP Records", val: run.total_erp },
              { label: "Statement Lines", val: run.total_statement },
              { label: "Matched", val: run.matched_count },
              { label: "Discrepancies", val: run.discrepancy_count },
              {
                label: "Match Rate",
                val:
                  run.auto_match_rate != null
                    ? `${run.auto_match_rate}%`
                    : "\u2014",
              },
            ].map((s, i) => (
              <div
                key={i}
                className="bg-card rounded-2xl p-3.5 text-center shadow-[0_1px_3px_rgba(0,0,0,0.04)]"
              >
                <div className="text-[11px] text-zinc-400 uppercase tracking-wider">{s.label}</div>
                {s.badge ? (
                  <div className="mt-1.5"><StatusBadge status={String(s.val)} /></div>
                ) : (
                  <div className="text-xl font-semibold mt-1 text-zinc-800">{s.val}</div>
                )}
              </div>
            ))}
          </div>
          {run.erp_not_in_statement > 0 && (
            <div className="text-xs text-zinc-500 border border-border rounded-lg px-4 py-2.5 mb-6 bg-muted">
              <span className="font-medium text-accent">{run.erp_not_in_statement} ERP records</span> were not included in the supplier statement and are excluded from the match rate.
            </div>
          )}
        </>
      )}

      {/* Results table */}
      {results.length > 0 && !loading && (
        <div className="bg-card rounded-2xl shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr className="text-xs text-zinc-400 uppercase tracking-wider">
                <th className="text-left px-4 py-2.5 font-medium">Match Type</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium">Discrepancy</th>
                <th className="text-right px-4 py-2.5 font-medium">Qty Delta</th>
                <th className="text-right px-4 py-2.5 font-medium">Price Delta</th>
                <th className="text-right px-4 py-2.5 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={r.id}
                  className="border-t border-border hover:bg-muted transition-colors"
                >
                  <td className="px-4 py-2.5 text-zinc-700">{r.match_type}</td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-2.5 text-zinc-500">
                    {r.discrepancy_type || "\u2014"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-zinc-600">
                    {r.quantity_delta?.toFixed(2) ?? "\u2014"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-zinc-600">
                    {r.price_delta?.toFixed(4) ?? "\u2014"}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-zinc-600">
                    {r.confidence?.toFixed(2) ?? "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
