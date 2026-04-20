"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";

interface Org {
  id: string;
  name: string;
}

interface Supplier {
  id: string;
  name: string;
  vendor_code: string;
}

export default function IngestionPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState("");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [supplierId, setSupplierId] = useState("");
  const [period, setPeriod] = useState("2026-03");

  // GRN state
  const [grnFile, setGrnFile] = useState<File | null>(null);
  const [grnStatus, setGrnStatus] = useState("");
  const [grnLoading, setGrnLoading] = useState(false);

  // Statement state
  const [stmtFile, setStmtFile] = useState<File | null>(null);
  const [stmtStatus, setStmtStatus] = useState("");
  const [stmtLoading, setStmtLoading] = useState(false);

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

  async function uploadGRN() {
    if (!grnFile || !orgId) return;
    setGrnLoading(true);
    setGrnStatus("");
    const fd = new FormData();
    fd.append("file", grnFile);
    fd.append("org_id", orgId);

    try {
      const res = await fetch("/api/v1/erp/upload-stream", {
        method: "POST",
        body: fd,
      });

      if (!res.ok) {
        const err = await res.json();
        setGrnStatus(`Error: ${err.detail || JSON.stringify(err)}`);
        setGrnLoading(false);
        return;
      }

      // Read SSE stream
      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;
            const data = JSON.parse(trimmed.slice(6));
            if (data.type === "progress") {
              setGrnStatus(data.message || "Processing...");
            } else if (data.type === "result") {
              finalResult = `Ingested: ${data.rows_ingested} rows, Skipped: ${data.rows_skipped}, Suppliers created: ${data.suppliers_created}`;
            }
          }
        }
      }

      setGrnStatus(finalResult || "Upload complete");
      // Reload suppliers
      fetch(`/api/v1/orgs/${orgId}/suppliers`)
        .then((r) => r.json())
        .then(setSuppliers)
        .catch(() => {});
    } catch (e) {
      setGrnStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setGrnLoading(false);
  }

  async function uploadStatement() {
    if (!stmtFile || !supplierId || !period) return;
    setStmtLoading(true);
    setStmtStatus("");
    const fd = new FormData();
    fd.append("file", stmtFile);
    fd.append("supplier_id", supplierId);
    fd.append("period", period);

    try {
      const res = await fetch("/api/v1/statements/upload", {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (res.ok) {
        setStmtStatus(
          `Ingested: ${data.rows_ingested} rows, Skipped: ${data.rows_skipped}, Mapping: ${data.mapping_source}`
        );
      } else {
        setStmtStatus(`Error: ${data.detail || JSON.stringify(data)}`);
      }
    } catch (e) {
      setStmtStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setStmtLoading(false);
  }

  return (
    <>
      <PageHeader
        title="Data Ingestion"
        description="Upload ERP goods receipt exports and supplier statements"
      />

      {/* Org selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium mb-1">Organization</label>
        <select
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full max-w-sm bg-white"
        >
          <option value="">Select...</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* GRN Upload */}
        <div className="border border-[var(--border)] rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-1">ERP / GRN Upload</h3>
          <p className="text-xs text-zinc-500 mb-4">
            Upload SGWERP goods receipt CSV/XLSX. Auto-creates suppliers.
          </p>

          <label className="block text-xs font-medium mb-1">GRN File</label>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setGrnFile(e.target.files?.[0] || null)}
            className="block w-full text-sm mb-3"
          />

          <button
            onClick={uploadGRN}
            disabled={!grnFile || !orgId || grnLoading}
            className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-40"
          >
            {grnLoading ? "Uploading..." : "Upload GRN"}
          </button>

          {grnStatus && (
            <div className="mt-3 text-xs p-3 bg-[var(--muted)] rounded font-mono whitespace-pre-wrap">
              {grnStatus}
            </div>
          )}
        </div>

        {/* Statement Upload */}
        <div className="border border-[var(--border)] rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-1">Supplier Statement</h3>
          <p className="text-xs text-zinc-500 mb-4">
            Upload a supplier reconciliation statement for matching.
          </p>

          <label className="block text-xs font-medium mb-1">Supplier</label>
          <select
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
            className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full bg-white mb-3"
          >
            <option value="">
              {suppliers.length === 0
                ? "Upload GRN first"
                : "Select supplier..."}
            </option>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.vendor_code})
              </option>
            ))}
          </select>

          <label className="block text-xs font-medium mb-1">Period</label>
          <input
            type="text"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="2026-03"
            className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full mb-3 bg-white"
          />

          <label className="block text-xs font-medium mb-1">
            Statement File
          </label>
          <input
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setStmtFile(e.target.files?.[0] || null)}
            className="block w-full text-sm mb-3"
          />

          <button
            onClick={uploadStatement}
            disabled={!stmtFile || !supplierId || !period || stmtLoading}
            className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-40"
          >
            {stmtLoading ? "Uploading..." : "Upload Statement"}
          </button>

          {stmtStatus && (
            <div className="mt-3 text-xs p-3 bg-[var(--muted)] rounded font-mono whitespace-pre-wrap">
              {stmtStatus}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
