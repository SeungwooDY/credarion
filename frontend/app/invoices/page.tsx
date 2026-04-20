"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import StatusBadge from "../components/status-badge";

interface Org {
  id: string;
  name: string;
}

interface InvoiceListItem {
  id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  total_amount: number | null;
  currency: string;
  status: string;
  supplier_name_extracted: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  created_at: string;
}

interface InvoiceDetail {
  id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  total_amount: number | null;
  subtotal: number | null;
  vat_rate: number | null;
  vat_amount: number | null;
  currency: string;
  status: string;
  supplier_id: string | null;
  supplier_name_extracted: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  field_confidences: Record<string, number> | null;
  original_filename: string | null;
  line_items: {
    id: string;
    description: string | null;
    quantity: number | null;
    unit_price: number | null;
    amount: number | null;
    po_number: string | null;
  }[];
}

export default function InvoicesPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState("");
  const [invoices, setInvoices] = useState<InvoiceListItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [reviewFilter, setReviewFilter] = useState("");
  const [selected, setSelected] = useState<InvoiceDetail | null>(null);

  // Upload state
  const [files, setFiles] = useState<FileList | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [extracting, setExtracting] = useState<string | null>(null);

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
    if (orgId) loadInvoices();
  }, [orgId, statusFilter, reviewFilter]);

  async function loadInvoices() {
    if (!orgId) return;
    let url = `/api/v1/invoices/?org_id=${orgId}&limit=100`;
    if (statusFilter) url += `&status=${statusFilter}`;
    if (reviewFilter) url += `&needs_review=${reviewFilter}`;

    try {
      const res = await fetch(url);
      if (res.ok) setInvoices(await res.json());
    } catch {
      /* ignore */
    }
  }

  async function handleUpload() {
    if (!files || !orgId) return;
    setUploading(true);
    setUploadMsg("");

    const fd = new FormData();
    for (let i = 0; i < files.length; i++) {
      fd.append("files", files[i]);
    }

    try {
      const res = await fetch(`/api/v1/invoices/upload?org_id=${orgId}`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (res.ok) {
        setUploadMsg(`Uploaded ${data.invoices.length} invoice(s)`);
        loadInvoices();
      } else {
        setUploadMsg(`Error: ${data.detail || JSON.stringify(data)}`);
      }
    } catch (e) {
      setUploadMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setUploading(false);
  }

  async function handleExtract(invoiceId: string) {
    setExtracting(invoiceId);
    try {
      const res = await fetch(`/api/v1/invoices/${invoiceId}/extract`, {
        method: "POST",
      });
      if (res.ok) {
        loadInvoices();
        // Open detail
        const detail = await res.json();
        setSelected(detail);
      } else {
        const err = await res.json();
        alert(`Extraction failed: ${err.detail || JSON.stringify(err)}`);
      }
    } catch (e) {
      alert(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
    setExtracting(null);
  }

  async function openDetail(id: string) {
    try {
      const res = await fetch(`/api/v1/invoices/${id}`);
      if (res.ok) setSelected(await res.json());
    } catch {
      /* ignore */
    }
  }

  async function transitionStatus(id: string, newStatus: string) {
    try {
      const res = await fetch(`/api/v1/invoices/${id}/status`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        const updated = await res.json();
        setSelected(updated);
        loadInvoices();
      } else {
        const err = await res.json();
        alert(err.detail || "Failed");
      }
    } catch {
      /* ignore */
    }
  }

  return (
    <>
      <PageHeader
        title="Invoice Processing"
        description="Upload fapiao images/PDFs for OCR extraction and processing"
      />

      {/* Upload section */}
      <div className="border border-[var(--border)] rounded-lg p-5 mb-6">
        <h3 className="font-semibold text-sm mb-3">Upload Invoices</h3>
        <div className="flex gap-4 items-end">
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
            <label className="block text-xs font-medium mb-1">
              Files (PNG, JPG, PDF)
            </label>
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.pdf"
              multiple
              onChange={(e) => setFiles(e.target.files)}
              className="text-sm"
            />
          </div>
          <button
            onClick={handleUpload}
            disabled={!files || !orgId || uploading}
            className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-40"
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </div>
        {uploadMsg && (
          <div className="mt-3 text-xs p-2 bg-[var(--muted)] rounded">
            {uploadMsg}
          </div>
        )}
      </div>

      <div className="flex gap-6">
        {/* Invoice list */}
        <div className="flex-1">
          <div className="flex gap-3 mb-4 items-center">
            <h3 className="font-semibold text-sm">Invoices</h3>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="border border-[var(--border)] rounded px-2 py-1 text-xs bg-white"
            >
              <option value="">All statuses</option>
              <option value="received">received</option>
              <option value="extracted">extracted</option>
              <option value="matched">matched</option>
              <option value="approved">approved</option>
              <option value="paid">paid</option>
            </select>
            <select
              value={reviewFilter}
              onChange={(e) => setReviewFilter(e.target.value)}
              className="border border-[var(--border)] rounded px-2 py-1 text-xs bg-white"
            >
              <option value="">All</option>
              <option value="true">Needs review</option>
              <option value="false">No review needed</option>
            </select>
          </div>

          {invoices.length === 0 ? (
            <div className="text-sm text-zinc-400 py-8 text-center border border-dashed border-[var(--border)] rounded-lg">
              No invoices yet. Upload some files above.
            </div>
          ) : (
            <div className="border border-[var(--border)] rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-[var(--muted)]">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Invoice #</th>
                    <th className="text-left px-3 py-2 font-medium">Date</th>
                    <th className="text-right px-3 py-2 font-medium">Amount</th>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium">Supplier</th>
                    <th className="px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr
                      key={inv.id}
                      className={`border-t border-[var(--border)] cursor-pointer hover:bg-[var(--muted)] ${
                        selected?.id === inv.id ? "bg-blue-50" : ""
                      }`}
                      onClick={() => openDetail(inv.id)}
                    >
                      <td className="px-3 py-2 font-mono text-xs">
                        {inv.invoice_number || "—"}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {inv.invoice_date || "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs">
                        {inv.total_amount != null
                          ? `${inv.currency} ${inv.total_amount.toLocaleString()}`
                          : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge status={inv.status} />
                      </td>
                      <td className="px-3 py-2 text-xs text-zinc-500">
                        {inv.supplier_name_extracted || "—"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {inv.status === "received" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleExtract(inv.id);
                            }}
                            disabled={extracting === inv.id}
                            className="text-xs px-2 py-1 bg-blue-600 text-white rounded disabled:opacity-40"
                          >
                            {extracting === inv.id ? "..." : "Extract"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-96 border border-[var(--border)] rounded-lg p-5 shrink-0 self-start">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-semibold text-sm">Invoice Detail</h3>
              <button
                onClick={() => setSelected(null)}
                className="text-xs text-zinc-400 hover:text-zinc-600"
              >
                Close
              </button>
            </div>

            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-zinc-500">Status</span>
                <StatusBadge status={selected.status} />
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Invoice #</span>
                <span className="font-mono text-xs">
                  {selected.invoice_number || "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Date</span>
                <span>{selected.invoice_date || "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Supplier</span>
                <span>{selected.supplier_name_extracted || "—"}</span>
              </div>

              <hr className="border-[var(--border)]" />

              <div className="flex justify-between">
                <span className="text-zinc-500">Subtotal</span>
                <span className="font-mono">
                  {selected.subtotal?.toLocaleString() ?? "—"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">VAT Rate</span>
                <span>{selected.vat_rate != null ? `${selected.vat_rate}%` : "—"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">VAT Amount</span>
                <span className="font-mono">
                  {selected.vat_amount?.toLocaleString() ?? "—"}
                </span>
              </div>
              <div className="flex justify-between font-medium">
                <span>Total</span>
                <span className="font-mono">
                  {selected.total_amount != null
                    ? `${selected.currency} ${selected.total_amount.toLocaleString()}`
                    : "—"}
                </span>
              </div>

              {/* Confidence */}
              {selected.extraction_confidence != null && (
                <>
                  <hr className="border-[var(--border)]" />
                  <div className="flex justify-between">
                    <span className="text-zinc-500">Confidence</span>
                    <span
                      className={`font-mono ${
                        selected.extraction_confidence < 0.8
                          ? "text-orange-600"
                          : "text-green-600"
                      }`}
                    >
                      {(selected.extraction_confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  {selected.needs_review && (
                    <div className="text-xs bg-orange-50 text-orange-700 p-2 rounded">
                      Needs manual review — some fields have low confidence
                    </div>
                  )}
                  {selected.field_confidences && (
                    <div className="text-xs space-y-1">
                      {Object.entries(selected.field_confidences).map(
                        ([field, conf]) => (
                          <div key={field} className="flex justify-between">
                            <span className="text-zinc-400">{field}</span>
                            <span
                              className={`font-mono ${
                                conf < 0.8 ? "text-orange-600" : "text-zinc-600"
                              }`}
                            >
                              {(conf * 100).toFixed(0)}%
                            </span>
                          </div>
                        )
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Line items */}
              {selected.line_items.length > 0 && (
                <>
                  <hr className="border-[var(--border)]" />
                  <div className="text-xs font-medium text-zinc-500 mb-2">
                    Line Items
                  </div>
                  {selected.line_items.map((li) => (
                    <div
                      key={li.id}
                      className="text-xs bg-[var(--muted)] rounded p-2 mb-1"
                    >
                      <div className="font-medium">
                        {li.description || "—"}
                      </div>
                      <div className="flex gap-3 text-zinc-500 mt-1">
                        <span>Qty: {li.quantity ?? "—"}</span>
                        <span>Price: {li.unit_price ?? "—"}</span>
                        <span>Amt: {li.amount ?? "—"}</span>
                      </div>
                      {li.po_number && (
                        <div className="text-zinc-400 mt-0.5">
                          PO: {li.po_number}
                        </div>
                      )}
                    </div>
                  ))}
                </>
              )}

              {/* Status actions */}
              <hr className="border-[var(--border)]" />
              <div className="flex gap-2">
                {selected.status === "received" && (
                  <button
                    onClick={() => handleExtract(selected.id)}
                    disabled={extracting === selected.id}
                    className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-40"
                  >
                    Extract OCR
                  </button>
                )}
                {selected.status === "extracted" && (
                  <>
                    <button
                      onClick={() =>
                        transitionStatus(selected.id, "matched")
                      }
                      className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded"
                    >
                      Mark Matched
                    </button>
                    <button
                      onClick={() =>
                        transitionStatus(selected.id, "approved")
                      }
                      className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded"
                    >
                      Approve
                    </button>
                  </>
                )}
                {selected.status === "matched" && (
                  <button
                    onClick={() =>
                      transitionStatus(selected.id, "approved")
                    }
                    className="text-xs px-3 py-1.5 bg-violet-600 text-white rounded"
                  >
                    Approve
                  </button>
                )}
                {selected.status === "approved" && (
                  <button
                    onClick={() => transitionStatus(selected.id, "paid")}
                    className="text-xs px-3 py-1.5 bg-green-600 text-white rounded"
                  >
                    Mark Paid
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
