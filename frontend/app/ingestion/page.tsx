"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import { useOrgs } from "../lib/swr";
import { CARD } from "@/app/lib/ui";
import { FileDropzone } from "@/components/ui/file-dropzone";
import { useT } from "@/app/lib/i18n";

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

const FIELD_LABEL_KEYS: Record<string, string> = {
  po_number: "ingestion.field_po_number",
  material_number: "ingestion.field_material_number",
  quantity: "common.quantity",
  unit_price: "common.unit_price",
  amount: "common.amount",
  delivery_date: "ingestion.field_delivery_date",
  delivery_note_ref: "ingestion.field_delivery_note",
};

export default function IngestionPage() {
  const t = useT();
  const { orgs } = useOrgs();
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
    if (orgs.length > 0 && !orgId) setOrgId(orgs[0].id);
  }, [orgs, orgId]);

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
              setGrnStatus(data.message || t("ingestion.processing"));
            } else if (data.type === "result") {
              finalResult = t("ingestion.grn_result", {
                ingested: data.rows_ingested,
                skipped: data.rows_skipped,
                created: data.suppliers_created,
              });
            }
          }
        }
      }

      setGrnStatus(finalResult || t("ingestion.upload_complete"));
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
          (replace ? t("ingestion.stmt_replaced_prefix") : "") +
            t("ingestion.stmt_result", {
              ingested: data.rows_ingested,
              skipped: data.rows_skipped,
            })
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

  // Shared dropzone strings (CSV/XLSX only — no docx/slides).
  const dzLabels = {
    click: t("ingestion.dropzone_click"),
    hint: t("ingestion.dropzone_hint"),
    formats: t("ingestion.dropzone_formats"),
    replace: t("ingestion.dropzone_replace"),
    remove: t("ingestion.dropzone_remove"),
  };

  const reverseMapping: Record<string, string> = {};
  if (preview?.column_mapping) {
    for (const [field, header] of Object.entries(preview.column_mapping)) {
      reverseMapping[header] = field;
    }
  }

  return (
    <>
      <PageHeader
        title={t("ingestion.title")}
        description={t("ingestion.description")}
      />

      {/* Org selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium mb-1">{t("ingestion.organization")}</label>
        <select
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          className="border border-border rounded-lg px-3 py-2 text-sm w-full max-w-sm bg-card focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
        >
          <option value="">{t("ingestion.select")}</option>
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* GRN Upload */}
        <div className={`${CARD} p-5`}>
          <h3 className="font-semibold text-sm mb-1">{t("ingestion.grn_card_title")}</h3>
          <p className="text-xs text-zinc-500 mb-4">
            {t("ingestion.grn_card_help")}
          </p>

          <label className="block text-xs font-medium mb-1">{t("ingestion.grn_file")}</label>
          <FileDropzone
            file={grnFile}
            accept=".csv,.xlsx,.xls"
            onSelect={setGrnFile}
            onRemove={() => setGrnFile(null)}
            disabled={grnLoading}
            labels={dzLabels}
            className="mb-3"
          />

          <button
            onClick={uploadGRN}
            disabled={!grnFile || !orgId || grnLoading}
            className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
          >
            {grnLoading ? t("ingestion.uploading") : t("ingestion.upload_grn")}
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
        <div className={`${CARD} p-5`}>
          <h3 className="font-semibold text-sm mb-1">{t("ingestion.stmt_card_title")}</h3>
          <p className="text-xs text-zinc-500 mb-4">
            {t("ingestion.stmt_card_help")}
          </p>

          {/* Step 1: File selection */}
          {stmtStep === "select" && (
            <>
              <label className="block text-xs font-medium mb-1">
                {t("ingestion.stmt_file")}
              </label>
              <FileDropzone
                file={stmtFile}
                accept=".csv,.xlsx,.xls"
                onSelect={setStmtFile}
                onRemove={() => setStmtFile(null)}
                disabled={stmtLoading}
                labels={dzLabels}
                className="mb-3"
              />

              <button
                onClick={handlePreview}
                disabled={!stmtFile || !orgId || stmtLoading}
                className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
              >
                {stmtLoading ? t("ingestion.analyzing") : t("ingestion.analyze_file")}
              </button>
            </>
          )}

          {/* Step 2: Preview & confirm */}
          {stmtStep === "preview" && preview && (
            <div className="space-y-4">
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs space-y-2">
                <p className="font-semibold text-blue-800">
                  {t("ingestion.auto_detected")}
                </p>

                <div>
                  <span className="text-blue-600">{t("ingestion.supplier_label")} </span>
                  {preview.matched_supplier_name ? (
                    <span className="font-medium text-blue-900">
                      {preview.matched_supplier_name}
                    </span>
                  ) : preview.detected_supplier_name ? (
                    <span className="text-amber-700">
                      &quot;{preview.detected_supplier_name}&quot; {t("ingestion.not_found_in_db")}
                    </span>
                  ) : (
                    <span className="text-zinc-400">{t("ingestion.could_not_detect")}</span>
                  )}
                </div>

                <div>
                  <span className="text-blue-600">{t("ingestion.period_label")} </span>
                  {preview.detected_period ? (
                    <span className="font-medium text-blue-900">
                      {preview.detected_period}
                    </span>
                  ) : (
                    <span className="text-zinc-400">{t("ingestion.could_not_detect")}</span>
                  )}
                </div>

                <div>
                  <span className="text-blue-600">{t("ingestion.data_rows_label")} </span>
                  <span className="font-medium text-blue-900">
                    {preview.total_data_rows}
                  </span>
                </div>

                <div>
                  <span className="text-blue-600">{t("ingestion.column_mapping_label")} </span>
                  {preview.column_mapping ? (
                    <span className="text-green-700 font-medium">
                      {t("ingestion.fields_mapped", { n: Object.keys(preview.column_mapping).length })}
                    </span>
                  ) : (
                    <span className="text-amber-700">
                      {t("ingestion.needs_manual_review")}
                    </span>
                  )}
                </div>
              </div>

              {preview.po_overlap?.warning && (
                <div className="border border-red-300 bg-red-50 rounded-lg p-3 text-xs">
                  <p className="font-semibold text-red-800 mb-1">
                    {t("ingestion.po_mismatch")}
                  </p>
                  <p className="text-red-700">
                    {preview.po_overlap.warning}
                  </p>
                  <p className="text-red-600 mt-1 font-mono">
                    {t("ingestion.file_pos")} {preview.po_overlap.file_po_count} | {t("ingestion.supplier_erp_pos")}{" "}
                    {preview.po_overlap.erp_po_count} | {t("ingestion.in_common")}{" "}
                    {preview.po_overlap.common_po_count} (
                    {preview.po_overlap.overlap_pct}%)
                  </p>
                </div>
              )}

              {!preview.matched_supplier_id && (
                <div className="text-xs p-3 border border-red-300 bg-red-50 rounded-lg">
                  <p className="font-semibold text-red-800">
                    {t("ingestion.could_not_match_supplier")}
                  </p>
                  <p className="text-red-700">
                    {t("ingestion.could_not_match_supplier_help")}
                  </p>
                </div>
              )}
              <div>
                <label className="block text-xs font-medium mb-1">
                  {t("common.period")}
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
                    {t("ingestion.preview_rows_count", {
                      shown: preview.preview_rows.length,
                      total: preview.total_data_rows,
                    })}
                  </p>
                  <div className={`overflow-x-auto ${CARD}`}>
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
                                  → {FIELD_LABEL_KEYS[reverseMapping[col]]
                                    ? t(FIELD_LABEL_KEYS[reverseMapping[col]])
                                    : reverseMapping[col]}
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
                    {t("ingestion.stmt_already_exists")}
                  </p>
                  <p className="text-amber-700 mb-2">
                    {t("ingestion.stmt_already_exists_help", {
                      date: new Date(duplicateInfo.upload_date).toLocaleDateString(),
                      count: duplicateInfo.row_count,
                    })}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleConfirmUpload(true)}
                      disabled={stmtLoading}
                      className="px-3 py-1.5 bg-amber-600 text-white rounded-lg text-xs font-medium disabled:opacity-40 transition-colors"
                    >
                      {stmtLoading ? t("ingestion.replacing") : t("ingestion.replace_existing")}
                    </button>
                    <button
                      onClick={() => setDuplicateInfo(null)}
                      className="px-3 py-1.5 border border-amber-300 text-amber-800 rounded-lg text-xs"
                    >
                      {t("common.cancel")}
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
                    {stmtLoading ? t("ingestion.uploading") : t("ingestion.confirm_upload")}
                  </button>
                  <button
                    onClick={resetStatement}
                    className="px-4 py-2 border border-border rounded-lg text-sm text-zinc-600 hover:bg-muted transition-colors"
                  >
                    {t("ingestion.start_over")}
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
                {t("ingestion.upload_another")}
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
