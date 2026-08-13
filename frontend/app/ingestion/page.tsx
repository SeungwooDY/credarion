"use client";

import { useState } from "react";
import { CalendarDays } from "lucide-react";
import PageHeader from "../components/page-header";
import { useCurrentOrg, useErpStatus } from "../lib/swr";
import { usePeriod } from "../lib/period";
import { PeriodBadge, usePeriodLabel } from "../components/period-switcher";
import MonthPicker from "../components/month-picker";
import { CARD } from "@/app/lib/ui";
import { FileDropzone, MultiFileDropzone } from "@/components/ui/file-dropzone";
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

interface BatchResult {
  name: string;
  status: "uploaded" | "skipped" | "error";
  message: string;
}

interface PeriodMismatch {
  pct: number;
  detected: string;
  selected: string;
}

// Compact month control: a labelled chip that toggles an inline calendar.
// Used by both upload flows so the filing month is always visible + editable.
function MonthField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (p: string) => void;
  disabled?: boolean;
}) {
  const label = usePeriodLabel(value);
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted disabled:opacity-40"
      >
        <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
        {label || value || "—"}
      </button>
      {open && (
        <div className="absolute z-40 mt-1 w-64 rounded-xl border border-border bg-card shadow-lg">
          <MonthPicker
            value={value}
            onSelect={(p) => {
              onChange(p);
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}

// Inline pre-upload warning: the statement's detected month differs from the
// chosen filing month; one click adopts the detected month.
function StatementPeriodWarning({
  detected,
  selected,
  onUseDetected,
}: {
  detected: string;
  selected: string;
  onUseDetected: () => void;
}) {
  const t = useT();
  const detectedLabel = usePeriodLabel(detected);
  const selectedLabel = usePeriodLabel(selected);
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-2.5 text-xs text-amber-800">
      <span>
        {t("ingestion.stmt_period_mismatch", {
          detected: detectedLabel,
          selected: selectedLabel,
        })}
      </span>
      <button
        type="button"
        onClick={onUseDetected}
        className="shrink-0 rounded-md border border-amber-400 px-2 py-1 font-medium transition-colors hover:bg-amber-100"
      >
        {t("ingestion.use_detected", { detected: detectedLabel })}
      </button>
    </div>
  );
}

// Amber post-ingest banner: the file's dates mostly belong to another month.
function PeriodMismatchBanner({ mismatch }: { mismatch: PeriodMismatch }) {
  const t = useT();
  const detectedLabel = usePeriodLabel(mismatch.detected);
  const selectedLabel = usePeriodLabel(mismatch.selected);
  return (
    <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
      <p className="mb-1 font-semibold">{t("ingestion.period_mismatch_title")}</p>
      <p>
        {t("ingestion.period_mismatch_body", {
          pct: mismatch.pct,
          detected: detectedLabel,
          selected: selectedLabel,
        })}
      </p>
    </div>
  );
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

// ERP/GRN upload card — the page's sole content until this month's ERP data
// is in; afterwards reachable via the top-right "Re-upload ERP" modal.
function GRNUploadCard({
  orgId,
  period,
  onUploaded,
}: {
  orgId: string;
  /** Accounting month the export is uploaded FOR — stamped onto every row;
      reconciliation scopes pairing by this tag, not by the rows' dates.
      Defaults to the globally selected month; editable per upload. */
  period: string;
  onUploaded?: () => void;
}) {
  const t = useT();
  const [grnFile, setGrnFile] = useState<File | null>(null);
  const [grnStatus, setGrnStatus] = useState("");
  const [grnLoading, setGrnLoading] = useState(false);
  const [grnReplace, setGrnReplace] = useState(false);
  const [grnPeriod, setGrnPeriod] = useState(period);
  const [mismatch, setMismatch] = useState<PeriodMismatch | null>(null);

  // Follow the global month when it changes (render-time state adjustment —
  // see react.dev "adjusting state when a prop changes").
  const [lastGlobalPeriod, setLastGlobalPeriod] = useState(period);
  if (period !== lastGlobalPeriod) {
    setLastGlobalPeriod(period);
    setGrnPeriod(period);
  }

  const dzLabels = {
    click: t("ingestion.dropzone_click"),
    hint: t("ingestion.dropzone_hint"),
    formats: t("ingestion.dropzone_formats"),
    replace: t("ingestion.dropzone_replace"),
    remove: t("ingestion.dropzone_remove"),
  };

  async function uploadGRN() {
    if (!grnFile || !orgId) return;
    setGrnLoading(true);
    setGrnStatus("");
    setMismatch(null);
    const fd = new FormData();
    fd.append("file", grnFile);
    fd.append("org_id", orgId);
    if (grnPeriod) fd.append("period", grnPeriod);
    if (grnReplace) fd.append("replace", "true");

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
              if (data.rows_replaced > 0) {
                finalResult += t("ingestion.grn_result_replaced", {
                  replaced: data.rows_replaced,
                });
              }
              if (data.period_warning && data.detected_period && data.period) {
                setMismatch({
                  pct: data.period_mismatch_pct,
                  detected: data.detected_period,
                  selected: data.period,
                });
              }
            }
          }
        }
      }

      setGrnStatus(finalResult || t("ingestion.upload_complete"));
      onUploaded?.();
    } catch (e) {
      setGrnStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setGrnLoading(false);
  }

  return (
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

      <label className="block text-xs font-medium mb-1">
        {t("ingestion.filing_month")}
      </label>
      <div className="mb-3">
        <MonthField value={grnPeriod} onChange={setGrnPeriod} disabled={grnLoading} />
      </div>

      <label className="flex items-center gap-2 mb-3 text-xs text-zinc-600 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={grnReplace}
          onChange={(e) => setGrnReplace(e.target.checked)}
          disabled={grnLoading}
          className="rounded"
        />
        {t("ingestion.grn_replace_existing")}
      </label>

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

      {mismatch && <PeriodMismatchBanner mismatch={mismatch} />}
    </div>
  );
}

export default function IngestionPage() {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const { period: globalPeriod } = usePeriod();
  const { hasErpData, erpRowCount, erpStatusLoading, refreshErpStatus } =
    useErpStatus(orgId, globalPeriod);
  const [erpModalOpen, setErpModalOpen] = useState(false);

  const [stmtFiles, setStmtFiles] = useState<File[]>([]);
  const [stmtIdx, setStmtIdx] = useState(0);
  const [batchResults, setBatchResults] = useState<BatchResult[]>([]);
  const [stmtStep, setStmtStep] = useState<"select" | "preview" | "done">("select");
  const [stmtLoading, setStmtLoading] = useState(false);
  const [stmtError, setStmtError] = useState("");
  const [preview, setPreview] = useState<PreviewData | null>(null);

  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateInfo | null>(null);

  // Record the outcome for file `idx`, then preview the next file in the
  // queue or show the summary when the batch is exhausted.
  function advance(idx: number, result: BatchResult) {
    setBatchResults((prev) => [...prev, result]);
    setPreview(null);
    setDuplicateInfo(null);
    setStmtError("");
    if (idx + 1 < stmtFiles.length) {
      void runPreview(idx + 1);
    } else {
      setStmtStep("done");
      setStmtLoading(false);
    }
  }

  async function runPreview(idx: number) {
    const file = stmtFiles[idx];
    if (!file || !orgId) return;
    setStmtIdx(idx);
    setStmtLoading(true);
    setStmtError("");
    setPreview(null);
    setDuplicateInfo(null);

    const fd = new FormData();
    fd.append("file", file);
    fd.append("org_id", orgId);

    try {
      const res = await fetch("/api/v1/statements/preview", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const err = await res.json();
        const msg =
          typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
        advance(idx, { name: file.name, status: "error", message: msg });
        return;
      }
      const data: PreviewData = await res.json();
      setPreview(data);
      // Default to the globally selected month — uploads file under the month
      // the user is working in. When the file's detected period disagrees, an
      // inline warning offers a one-click switch to the detected month.
      setSelectedPeriod(globalPeriod || data.detected_period || "");
      setStmtStep("preview");
      setStmtLoading(false);
    } catch (e) {
      advance(idx, {
        name: file.name,
        status: "error",
        message: e instanceof Error ? e.message : String(e),
      });
    }
  }

  async function handleConfirmUpload(replace = false) {
    const file = stmtFiles[stmtIdx];
    const supplierId = preview?.matched_supplier_id;
    if (!file || !supplierId || !selectedPeriod) return;
    setStmtLoading(true);
    setStmtError("");
    setDuplicateInfo(null);

    const fd = new FormData();
    fd.append("file", file);
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
        advance(stmtIdx, {
          name: file.name,
          status: "uploaded",
          message:
            (replace ? t("ingestion.stmt_replaced_prefix") : "") +
            t("ingestion.stmt_result", {
              ingested: data.rows_ingested,
              skipped: data.rows_skipped,
            }),
        });
      } else if (res.status === 409) {
        setDuplicateInfo(data.detail?.existing || null);
        setStmtLoading(false);
      } else {
        const msg = typeof data.detail === "string" ? data.detail : data.detail?.message || JSON.stringify(data);
        setStmtError(msg);
        setStmtLoading(false);
      }
    } catch (e) {
      setStmtError(`Error: ${e instanceof Error ? e.message : String(e)}`);
      setStmtLoading(false);
    }
  }

  function skipCurrent() {
    const file = stmtFiles[stmtIdx];
    if (!file) return;
    advance(stmtIdx, { name: file.name, status: "skipped", message: "" });
  }

  function resetStatement() {
    setStmtFiles([]);
    setStmtIdx(0);
    setBatchResults([]);
    setStmtStep("select");
    setStmtLoading(false);
    setStmtError("");
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

      {/* Active period + ERP re-upload (top-right, once ERP data is in) */}
      <div className="mb-6 flex items-center justify-between">
        <PeriodBadge />
        {hasErpData && (
          <div className="flex items-center gap-3">
            <span className="text-xs text-zinc-400">
              {t("ingestion.erp_rows_loaded", { n: erpRowCount })}
            </span>
            <button
              onClick={() => setErpModalOpen(true)}
              className="px-3 py-1.5 text-xs border border-border rounded-lg text-zinc-600 hover:bg-muted transition-colors"
            >
              {t("ingestion.reupload_erp")}
            </button>
          </div>
        )}
      </div>

      {/* Gate: ERP export first — statements unlock once this month's
          receipts are in (they need the suppliers + GRN rows to match). */}
      {!hasErpData && !erpStatusLoading && (
        <div className="max-w-xl mx-auto">
          <div className="mb-4 text-xs p-3 rounded-lg border border-blue-200 bg-blue-50 text-blue-800">
            {t("ingestion.erp_first_hint", { period: globalPeriod })}
          </div>
          <GRNUploadCard orgId={orgId} period={globalPeriod} onUploaded={refreshErpStatus} />
        </div>
      )}

      {hasErpData && (
        <div className="max-w-2xl mx-auto">
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
              <MultiFileDropzone
                files={stmtFiles}
                accept=".csv,.xlsx,.xls"
                onAdd={(added) =>
                  setStmtFiles((prev) => {
                    const seen = new Set(prev.map((f) => `${f.name}|${f.size}`));
                    return [
                      ...prev,
                      ...added.filter((f) => !seen.has(`${f.name}|${f.size}`)),
                    ];
                  })
                }
                onRemoveAt={(i) =>
                  setStmtFiles((prev) => prev.filter((_, j) => j !== i))
                }
                disabled={stmtLoading}
                labels={dzLabels}
                className="mb-3"
              />

              <button
                onClick={() => {
                  setBatchResults([]);
                  void runPreview(0);
                }}
                disabled={!stmtFiles.length || !orgId || stmtLoading}
                className="px-4 py-2 bg-accent hover:bg-accent-dark text-white rounded-lg text-sm disabled:opacity-40 transition-colors"
              >
                {stmtLoading
                  ? t("ingestion.analyzing")
                  : stmtFiles.length > 1
                    ? t("ingestion.analyze_files", { n: stmtFiles.length })
                    : t("ingestion.analyze_file")}
              </button>
            </>
          )}

          {/* Step 2: Preview & confirm */}
          {stmtStep === "preview" && preview && (
            <div className="space-y-4">
              {stmtFiles.length > 1 && (
                <p className="text-xs font-medium text-zinc-500">
                  {t("ingestion.file_x_of_n", {
                    i: stmtIdx + 1,
                    n: stmtFiles.length,
                  })}{" "}
                  <span className="font-mono text-zinc-700">
                    {stmtFiles[stmtIdx]?.name}
                  </span>
                </p>
              )}
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
                <MonthField
                  value={selectedPeriod}
                  onChange={setSelectedPeriod}
                  disabled={stmtLoading}
                />
                {preview.detected_period &&
                  selectedPeriod &&
                  preview.detected_period !== selectedPeriod && (
                    <StatementPeriodWarning
                      detected={preview.detected_period}
                      selected={selectedPeriod}
                      onUseDetected={() =>
                        setSelectedPeriod(preview.detected_period!)
                      }
                    />
                  )}
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
                    {stmtFiles.length > 1 && (
                      <button
                        onClick={skipCurrent}
                        disabled={stmtLoading}
                        className="px-3 py-1.5 border border-amber-300 text-amber-800 rounded-lg text-xs disabled:opacity-40"
                      >
                        {t("ingestion.skip_file")}
                      </button>
                    )}
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
                  {stmtFiles.length > 1 && (
                    <button
                      onClick={skipCurrent}
                      disabled={stmtLoading}
                      className="px-4 py-2 border border-border rounded-lg text-sm text-zinc-600 hover:bg-muted transition-colors disabled:opacity-40"
                    >
                      {t("ingestion.skip_file")}
                    </button>
                  )}
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

          {/* Step 3: Done — per-file batch summary */}
          {stmtStep === "done" && (
            <div className="space-y-3">
              {batchResults.length > 1 && (
                <p className="text-xs font-medium text-zinc-600">
                  {t("ingestion.batch_summary")}
                </p>
              )}
              <ul className="space-y-1.5">
                {batchResults.map((r, i) => (
                  <li
                    key={i}
                    className={`text-xs p-3 rounded-lg border font-mono ${
                      r.status === "uploaded"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : r.status === "skipped"
                          ? "bg-zinc-50 text-zinc-600 border-zinc-200"
                          : "bg-red-50 text-red-700 border-red-200"
                    }`}
                  >
                    <span className="font-medium">{r.name}</span>
                    {": "}
                    {r.status === "uploaded"
                      ? r.message
                      : r.status === "skipped"
                        ? t("ingestion.status_skipped")
                        : `${t("ingestion.status_error")}${r.message ? ` — ${r.message}` : ""}`}
                  </li>
                ))}
              </ul>
              {batchResults.some((r) => r.status === "uploaded") && (
                <p className="text-xs text-zinc-500">
                  {t("ingestion.auto_recon_note")}
                </p>
              )}
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
      )}

      {/* Re-upload ERP modal */}
      {erpModalOpen && (
        <div
          className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-6"
          onClick={() => setErpModalOpen(false)}
        >
          <div
            className="w-full max-w-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <GRNUploadCard orgId={orgId} period={globalPeriod} onUploaded={refreshErpStatus} />
            <button
              onClick={() => setErpModalOpen(false)}
              className="mt-3 px-4 py-2 border border-border bg-card rounded-lg text-sm text-zinc-600 hover:bg-muted transition-colors"
            >
              {t("common.close")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
