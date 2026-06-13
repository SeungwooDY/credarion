"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";

interface Org {
  id: string;
  name: string;
}

interface POOverlapInfo {
  file_po_count: number;
  erp_po_count: number;
  common_po_count: number;
  overlap_pct: number;
  warning: string | null;
}

interface PreviewData {
  detected_supplier_name: string | null;
  matched_supplier_id: string | null;
  matched_supplier_name: string | null;
  detected_period: string | null;
  header_row: number;
  columns: string[];
  column_mapping: Record<string, string> | null;
  preview_rows: Record<string, string>[];
  total_data_rows: number;
  temp_file: string;
  po_overlap: POOverlapInfo | null;
}

interface DuplicateInfo {
  statement_id: string;
  period: string;
  upload_date: string;
  row_count: number;
}

const FIELD_LABELS: Record<string, string> = {
  po_number: "PO Number",
  material_number: "Material #",
  quantity: "Quantity",
  unit_price: "Unit Price",
  amount: "Amount",
  delivery_date: "Delivery Date",
  delivery_note_ref: "Delivery Note",
};

export default function IngestionPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState("");

  const [grnFile, setGrnFile] = useState<File | null>(null);
  const [grnStatus, setGrnStatus] = useState("");
  const [grnLoading, setGrnLoading] = useState(false);

  const [stmtFile, setStmtFile] = useState<File | null>(null);
  const [stmtStep, setStmtStep] = useState<"select" | "preview" | "done">("select");
  const [stmtLoading, setStmtLoading] = useState(false);
  const [stmtError, setStmtError] = useState("");
  const [stmtResult, setStmtResult] = useState("");
  const [preview, setPreview] = useState<PreviewData | null>(null);

  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateInfo | null>(null);

  useEffect(() => {
    fetch("/api/v1/orgs")
      .then((r) => r.json())
      .then((data) => {
        setOrgs(data);
        if (data.length > 0) setOrgId(data[0].id);
      })
      .catch(() => {});
  }, []);

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
    } catch (e) {
      setGrnStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setGrnLoading(false);
  }

  async function handlePreview() {
    if (!stmtFile || !orgId) return;
    setStmtLoading(true);
    setStmtError("");
    setPreview(null);
    setDuplicateInfo(null);

    const fd = new FormData();
    fd.append("file", stmtFile);
    fd.append("org_id", orgId);

    try {
      const res = await fetch("/api/v1/statements/preview", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json();
        setStmtError(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
        setStmtLoading(false);
        return;
      }
      const data: PreviewData = await res.json();
      setPreview(data);
      setSelectedPeriod(data.detected_period || "");
      setStmtStep("preview");
    } catch (e) {
      setStmtError(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setStmtLoading(false);
  }

  async function handleConfirmUpload(replace = false) {
    const supplierId = preview?.matched_supplier_id;
    if (!stmtFile || !supplierId || !selectedPeriod) return;
    setStmtLoading(true);
    setStmtError("");
    setDuplicateInfo(null);

    const fd = new FormData();
    fd.append("file", stmtFile);
    fd.append("supplier_id", supplierId);
    fd.append("period", selectedPeriod);
    if (replace) fd.append("replace", "true");

    try {
      const res = await fetch("/api/v1/statements/upload", {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (res.ok) {
        setStmtResult(
          `${replace ? "Replaced previous statement. " : ""}Ingested ${data.rows_ingested} rows, skipped ${data.rows_skipped}`
        );
        setStmtStep("done");
      } else if (res.status === 409) {
        setDuplicateInfo(data.detail?.existing || null);
      } else {
        const msg = typeof data.detail === "string" ? data.detail : data.detail?.message || JSON.stringify(data);
        setStmtError(msg);
      }
    } catch (e) {
      setStmtError(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setStmtLoading(false);
  }

  function resetStatement() {
    setStmtFile(null);
    setStmtStep("select");
    setStmtLoading(false);
    setStmtError("");
    setStmtResult("");
    setPreview(null);
    setSelectedPeriod("");
    setDuplicateInfo(null);
  }

  const reverseMapping: Record<string, string> = {};
  if (preview?.column_mapping) {
    for (const [field, header] of Object.entries(preview.column_mapping)) {
      reverseMapping[header] = field;
    }
  }

  return (
    <>
      <PageHeader
        title="Data Ingestion"
        description="Upload ERP goods receipt exports and supplier reconciliation statements"
      />

      {/* Org selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium mb-1">Organization</label>
        <select
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          className="border border-border rounded-lg px-3 py-2 text-sm w-full max-w-sm bg-card focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
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
        <div className="bg-card rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <h3 className="font-semibold text-sm mb-1">ERP / GRN Upload</h3>
          <p className="text-xs text-zinc-500 mb-4">
            Upload your SGWERP goods receipt CSV/XLSX. This is your internal
            record of what was received. Suppliers are auto-created from vendor
            data in the file.
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
            className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
          >
            {grnLoading ? "Uploading..." : "Upload GRN"}
          </button>

          {grnStatus && (
            <div
              className={`mt-3 text-xs p-3 rounded-lg font-mono whitespace-pre-wrap ${
                grnStatus.startsWith("Error")
                  ? "bg-red-50 text-red-700 border border-red-200"
                  : "bg-green-50 text-green-700 border border-green-200"
              }`}
            >
              {grnStatus}
            </div>
          )}
        </div>

        {/* Statement Upload */}
        <div className="bg-card rounded-2xl p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
          <h3 className="font-semibold text-sm mb-1">Supplier Statement</h3>
          <p className="text-xs text-zinc-500 mb-4">
            Upload a reconciliation statement (对账单) received from a supplier.
            The system will auto-detect the supplier, period, and column
            structure.
          </p>

          {/* Step 1: File selection */}
          {stmtStep === "select" && (
            <>
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
                onClick={handlePreview}
                disabled={!stmtFile || !orgId || stmtLoading}
                className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
              >
                {stmtLoading ? "Analyzing file..." : "Analyze File"}
              </button>
            </>
          )}

          {/* Step 2: Preview & confirm */}
          {stmtStep === "preview" && preview && (
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs space-y-2">
                <p className="font-semibold text-blue-800">
                  Auto-detected from file
                </p>

                <div>
                  <span className="text-blue-600">Supplier: </span>
                  {preview.matched_supplier_name ? (
                    <span className="font-medium text-blue-900">
                      {preview.matched_supplier_name}
                    </span>
                  ) : preview.detected_supplier_name ? (
                    <span className="text-amber-700">
                      &quot;{preview.detected_supplier_name}&quot; (not found in
                      database)
                    </span>
                  ) : (
                    <span className="text-zinc-400">Could not detect</span>
                  )}
                </div>

                <div>
                  <span className="text-blue-600">Period: </span>
                  {preview.detected_period ? (
                    <span className="font-medium text-blue-900">
                      {preview.detected_period}
                    </span>
                  ) : (
                    <span className="text-zinc-400">Could not detect</span>
                  )}
                </div>

                <div>
                  <span className="text-blue-600">Data rows: </span>
                  <span className="font-medium text-blue-900">
                    {preview.total_data_rows}
                  </span>
                </div>

                <div>
                  <span className="text-blue-600">Column mapping: </span>
                  {preview.column_mapping ? (
                    <span className="text-green-700 font-medium">
                      {Object.keys(preview.column_mapping).length} fields mapped
                    </span>
                  ) : (
                    <span className="text-amber-700">
                      Needs manual review
                    </span>
                  )}
                </div>
              </div>

              {preview.po_overlap?.warning && (
                <div className="border border-red-300 bg-red-50 rounded-lg p-3 text-xs">
                  <p className="font-semibold text-red-800 mb-1">
                    PO Number Mismatch
                  </p>
                  <p className="text-red-700">
                    {preview.po_overlap.warning}
                  </p>
                  <p className="text-red-600 mt-1 font-mono">
                    File POs: {preview.po_overlap.file_po_count} | Supplier ERP
                    POs: {preview.po_overlap.erp_po_count} | In common:{" "}
                    {preview.po_overlap.common_po_count} (
                    {preview.po_overlap.overlap_pct}%)
                  </p>
                </div>
              )}

              {!preview.matched_supplier_id && (
                <div className="text-xs p-3 border border-red-300 bg-red-50 rounded-lg">
                  <p className="font-semibold text-red-800">
                    Could not match supplier to database
                  </p>
                  <p className="text-red-700">
                    Upload GRN data first so the supplier exists, or check that the
                    statement has a company name (供货单位) in the header rows.
                  </p>
                </div>
              )}
              <div>
                <label className="block text-xs font-medium mb-1">
                  Period
                </label>
                <input
                  type="text"
                  value={selectedPeriod}
                  onChange={(e) => setSelectedPeriod(e.target.value)}
                  placeholder="2026-03"
                  className="border border-border rounded-lg px-3 py-2 text-sm w-full max-w-[200px] bg-card focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
                />
              </div>

              {preview.preview_rows.length > 0 && (
                <div>
                  <p className="text-xs font-medium mb-2 text-zinc-600">
                    Preview (first {preview.preview_rows.length} of{" "}
                    {preview.total_data_rows} rows)
                  </p>
                  <div className="overflow-x-auto bg-card rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-muted">
                          {preview.columns.map((col) => (
                            <th
                              key={col}
                              className="text-left px-2 py-1.5 font-medium whitespace-nowrap"
                            >
                              <div>{col}</div>
                              {reverseMapping[col] && (
                                <div className="font-normal text-accent">
                                  → {FIELD_LABELS[reverseMapping[col]] || reverseMapping[col]}
                                </div>
                              )}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.preview_rows.map((row, i) => (
                          <tr
                            key={i}
                            className="border-t border-border"
                          >
                            {preview.columns.map((col) => (
                              <td
                                key={col}
                                className="px-2 py-1.5 font-mono whitespace-nowrap"
                              >
                                {row[col] || ""}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {duplicateInfo && (
                <div className="text-xs p-3 border border-amber-300 bg-amber-50 rounded-lg">
                  <p className="font-semibold text-amber-800 mb-1">
                    Statement already exists
                  </p>
                  <p className="text-amber-700 mb-2">
                    A statement for this supplier and period was uploaded on{" "}
                    {new Date(duplicateInfo.upload_date).toLocaleDateString()}{" "}
                    with {duplicateInfo.row_count} line items. Replacing will
                    delete the previous data.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleConfirmUpload(true)}
                      disabled={stmtLoading}
                      className="px-3 py-1.5 bg-amber-600 text-white rounded-lg text-xs font-medium disabled:opacity-40 transition-colors"
                    >
                      {stmtLoading ? "Replacing..." : "Replace existing"}
                    </button>
                    <button
                      onClick={() => setDuplicateInfo(null)}
                      className="px-3 py-1.5 border border-amber-300 text-amber-800 rounded-lg text-xs"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}

              {!duplicateInfo && (
                <div className="flex gap-2">
                  <button
                    onClick={() => handleConfirmUpload(false)}
                    disabled={
                      !preview?.matched_supplier_id || !selectedPeriod || stmtLoading
                    }
                    className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
                  >
                    {stmtLoading ? "Uploading..." : "Confirm & Upload"}
                  </button>
                  <button
                    onClick={resetStatement}
                    className="px-4 py-2 border border-border rounded-lg text-sm text-zinc-600 hover:bg-muted transition-colors"
                  >
                    Start over
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Done */}
          {stmtStep === "done" && (
            <div className="space-y-3">
              <div className="text-xs p-3 bg-green-50 text-green-700 border border-green-200 rounded-lg font-mono">
                {stmtResult}
              </div>
              <button
                onClick={resetStatement}
                className="px-4 py-2 border border-border rounded-lg text-sm text-zinc-600 hover:bg-muted transition-colors"
              >
                Upload another statement
              </button>
            </div>
          )}

          {stmtError && (
            <div className="mt-3 text-xs p-3 bg-red-50 text-red-700 border border-red-200 rounded-lg">
              {stmtError}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
