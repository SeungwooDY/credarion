"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import StatusBadge from "../components/status-badge";

interface Org {
  id: string;
  name: string;
}

interface Supplier {
  id: string;
  name: string;
  vendor_code: string;
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
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [period, setPeriod] = useState("2026-03");
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

  useEffect(() => {
    if (!orgId) return;
    fetch(`/api/v1/orgs/${orgId}/suppliers`)
      .then((r) => r.json())
      .then(setSuppliers)
      .catch(() => setSuppliers([]));
  }, [orgId]);

  async function runReconciliation() {
    if (!supplierId || !period) return;
    setLoading(true);
    setError("");
    setRunResult(null);
    setResults([]);

    try {
      const res = await fetch("/api/v1/reconciliation/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ supplier_id: supplierId, period }),
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
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setLoading(false);
  }

  const run = runResult?.run;

  return (
    <>
      <PageHeader
        title="Reconciliation"
        description="Run the 4-layer matching engine: exact, fuzzy, delivery note, AI"
      />

      {/* Controls */}
      <div className="flex gap-4 items-end mb-6">
        <div>
          <label className="block text-xs font-medium mb-1">Organization</label>
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
          <label className="block text-xs font-medium mb-1">Supplier</label>
          <select
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
            className="border border-[var(--border)] rounded px-3 py-2 text-sm bg-white"
          >
            <option value="">Select...</option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
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
        <button
          onClick={runReconciliation}
          disabled={!supplierId || loading}
          className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-40"
        >
          {loading ? "Running..." : "Run Reconciliation"}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-600 bg-red-50 p-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Summary stats */}
      {run && (
        <div className="grid grid-cols-6 gap-3 mb-6">
          {[
            { label: "Status", val: run.status, badge: true },
            { label: "ERP Records", val: run.total_erp },
            { label: "Statement Lines", val: run.total_statement },
            { label: "Matched", val: run.matched_count },
            { label: "Discrepancies", val: run.discrepancy_count },
            {
              label: "Match Rate",
              val: run.auto_match_rate != null ? `${run.auto_match_rate}%` : "—",
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
