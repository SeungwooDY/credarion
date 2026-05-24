"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import StatusBadge from "../components/status-badge";

interface Org {
  id: string;
  name: string;
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

interface RunResult {
  run: {
    id: string;
    status: string;
    total_erp: number;
    total_statement: number;
    matched_count: number;
    discrepancy_count: number;
    unmatched_count: number;
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

export default function ReconciliationPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState("");
  const [period, setPeriod] = useState("2026-03");
  const [suppliers, setSuppliers] = useState<SupplierReady[]>([]);
  const [suppliersLoading, setSuppliersLoading] = useState(false);

  const [supplierId, setSupplierId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [results, setResults] = useState<ResultRow[]>([]);

  useEffect(() => {
    fetch("/api/v1/orgs")
      .then((r) => r.json())
      .then((data) => {
        setOrgs(data);
        if (data.length > 0) setOrgId(data[0].id);
      })
      .catch(() => {});
  }, []);

  // Load suppliers with readiness when org or period changes
  useEffect(() => {
    if (!orgId || !period) return;
    setSuppliersLoading(true);
    fetch(
      `/api/v1/reconciliation/suppliers-ready?org_id=${orgId}&period=${period}`
    )
      .then((r) => r.json())
      .then((data) => {
        setSuppliers(data);
        setSuppliersLoading(false);
      })
      .catch(() => {
        setSuppliers([]);
        setSuppliersLoading(false);
      });
  }, [orgId, period]);

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

      // Load results
      const resResults = await fetch(
        `/api/v1/reconciliation/results?run_id=${data.run.id}&limit=100`
      );
      if (resResults.ok) {
        setResults(await resResults.json());
      }

      // Refresh supplier list to update last_match_rate
      fetch(
        `/api/v1/reconciliation/suppliers-ready?org_id=${orgId}&period=${period}`
      )
        .then((r) => r.json())
        .then(setSuppliers)
        .catch(() => {});
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
          <label className="block text-xs font-medium mb-1">
            Organization
          </label>
          <select
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            className="border border-[var(--border)] rounded px-3 py-2 text-sm bg-white"
          >
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1">Period</label>
          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="border border-[var(--border)] rounded px-3 py-2 text-sm bg-white w-28"
          />
        </div>
      </div>

      {/* Supplier readiness table */}
      <div className="border border-[var(--border)] rounded-lg overflow-hidden mb-6">
        <div className="bg-[var(--muted)] px-4 py-2.5 flex items-center justify-between">
          <h3 className="text-sm font-semibold">
            Suppliers for {period}
          </h3>
          {!suppliersLoading && (
            <div className="text-xs text-zinc-500">
              <span className="text-green-600 font-medium">{readyCount} ready</span>
              {notReadyCount > 0 && (
                <span className="ml-2 text-zinc-400">
                  {notReadyCount} missing data
                </span>
              )}
            </div>
          )}
        </div>

        {suppliersLoading ? (
          <div className="p-4 text-sm text-zinc-400">Loading suppliers...</div>
        ) : suppliers.length === 0 ? (
          <div className="p-4 text-sm text-zinc-400">
            No suppliers with data for this period. Upload GRN and statements
            first.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)] text-xs text-zinc-500">
                <th className="text-left px-4 py-2 font-medium">Supplier</th>
                <th className="text-right px-4 py-2 font-medium">
                  ERP Records
                </th>
                <th className="text-right px-4 py-2 font-medium">
                  Statement Rows
                </th>
                <th className="text-center px-4 py-2 font-medium">Status</th>
                <th className="text-right px-4 py-2 font-medium">
                  Last Match Rate
                </th>
                <th className="text-center px-4 py-2 font-medium">Action</th>
              </tr>
            </thead>
            <tbody>
              {suppliers.map((s) => (
                <tr
                  key={s.id}
                  className={`border-t border-[var(--border)] ${
                    s.id === supplierId ? "bg-blue-50" : "hover:bg-[var(--muted)]"
                  } ${!s.ready ? "opacity-60" : ""}`}
                >
                  <td className="px-4 py-2.5">
                    <div className="font-medium">{s.name}</div>
                    <div className="text-xs text-zinc-400">{s.vendor_code}</div>
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {s.erp_count > 0 ? (
                      s.erp_count
                    ) : (
                      <span className="text-red-400">0</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {s.statement_rows > 0 ? (
                      s.statement_rows
                    ) : (
                      <span className="text-red-400">
                        No statement
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {s.ready ? (
                      <span className="inline-block text-xs px-2 py-0.5 rounded bg-green-50 text-green-700 border border-green-200">
                        Ready
                      </span>
                    ) : !s.has_statement ? (
                      <span className="inline-block text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                        No statement
                      </span>
                    ) : (
                      <span className="inline-block text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                        No ERP data
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {s.last_match_rate != null ? (
                      <span
                        className={
                          s.last_match_rate >= 90
                            ? "text-green-600"
                            : s.last_match_rate >= 50
                              ? "text-amber-600"
                              : "text-red-500"
                        }
                      >
                        {s.last_match_rate.toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-zinc-300">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <button
                      onClick={() => runReconciliation(s.id)}
                      disabled={!s.ready || loading}
                      className="px-3 py-1 text-xs bg-[var(--accent)] text-white rounded disabled:opacity-30 disabled:cursor-not-allowed"
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

      {error && (
        <div className="text-sm text-red-600 bg-red-50 p-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Summary stats */}
      {run && (
        <>
          <h3 className="text-sm font-semibold mb-3">
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
                    : "���",
              },
            ].map((s, i) => (
              <div
                key={i}
                className="border border-[var(--border)] rounded-lg p-3 text-center"
              >
                <div className="text-xs text-zinc-500">{s.label}</div>
                {s.badge ? (
                  <StatusBadge status={String(s.val)} />
                ) : (
                  <div className="text-lg font-semibold mt-1">{s.val}</div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <div className="border border-[var(--border)] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--muted)]">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Match Type</th>
                <th className="text-left px-4 py-2 font-medium">Status</th>
                <th className="text-left px-4 py-2 font-medium">
                  Discrepancy
                </th>
                <th className="text-right px-4 py-2 font-medium">Qty Delta</th>
                <th className="text-right px-4 py-2 font-medium">
                  Price Delta
                </th>
                <th className="text-right px-4 py-2 font-medium">
                  Confidence
                </th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={r.id}
                  className="border-t border-[var(--border)] hover:bg-[var(--muted)]"
                >
                  <td className="px-4 py-2">{r.match_type}</td>
                  <td className="px-4 py-2">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-2 text-zinc-500">
                    {r.discrepancy_type || "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {r.quantity_delta?.toFixed(2) ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {r.price_delta?.toFixed(4) ?? "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-mono">
                    {r.confidence?.toFixed(2) ?? "—"}
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
