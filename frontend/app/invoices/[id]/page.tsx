"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import PageHeader from "../../components/page-header";
import StatusBadge from "../../components/status-badge";

interface InvoiceDetail {
  id: string;
  org_id: string;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  total_amount: number | null;
  subtotal: number | null;
  vat_rate: number | null;
  vat_amount: number | null;
  currency: string;
  status: string;
  file_url: string;
  file_type: string;
  original_filename: string | null;
  supplier_id: string | null;
  supplier_name_extracted: string | null;
  needs_review: boolean;
  extraction_confidence: number | null;
  field_confidences: Record<string, number> | null;
  extracted_at: string | null;
  created_at: string;
  updated_at: string;
  line_items: LineItem[];
}

interface LineItem {
  id: string;
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  po_number: string | null;
  material_number: string | null;
}

const TRANSITIONS: Record<string, string[]> = {
  received: ["extracted"],
  extracted: ["matched", "approved"],
  matched: ["approved"],
  approved: ["paid"],
};

export default function InvoiceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [editFields, setEditFields] = useState<Record<string, string>>({});

  const id = params?.id as string;

  useEffect(() => {
    if (!id) return;
    fetch(`/api/v1/invoices/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error("Not found");
        return r.json();
      })
      .then(setInvoice)
      .catch((e) => setError(e.message));
  }, [id]);

  async function handleExtract() {
    const res = await fetch(`/api/v1/invoices/${id}/extract`, {
      method: "POST",
    });
    if (res.ok) setInvoice(await res.json());
    else {
      const err = await res.json();
      alert(err.detail);
    }
  }

  async function handleTransition(status: string) {
    const res = await fetch(`/api/v1/invoices/${id}/status`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    if (res.ok) setInvoice(await res.json());
    else {
      const err = await res.json();
      alert(err.detail);
    }
  }

  async function saveEdits() {
    const body: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(editFields)) {
      if (v !== "") body[k] = v;
    }
    const res = await fetch(`/api/v1/invoices/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      setInvoice(await res.json());
      setEditing(false);
      setEditFields({});
    }
  }

  if (error) {
    return (
      <>
        <PageHeader title="Invoice Not Found" />
        <p className="text-sm text-red-600">{error}</p>
        <button
          onClick={() => router.push("/invoices")}
          className="mt-4 text-sm text-blue-600 underline"
        >
          Back to invoices
        </button>
      </>
    );
  }

  if (!invoice) {
    return (
      <>
        <PageHeader title="Invoice" />
        <p className="text-sm text-zinc-400">Loading...</p>
      </>
    );
  }

  const allowed = TRANSITIONS[invoice.status] || [];

  return (
    <>
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={() => router.push("/invoices")}
          className="text-sm text-zinc-500 hover:text-zinc-800"
        >
          &larr; Back
        </button>
        <h2 className="text-xl font-semibold">
          Invoice {invoice.invoice_number || invoice.id.slice(0, 8)}
        </h2>
        <StatusBadge status={invoice.status} />
        {invoice.needs_review && (
          <span className="text-xs bg-orange-50 text-orange-700 px-2 py-0.5 rounded">
            Needs Review
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Main info */}
        <div className="col-span-2 space-y-6">
          {/* Fields */}
          <div className="border border-[var(--border)] rounded-lg p-5">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-semibold text-sm">Extracted Fields</h3>
              {!editing ? (
                <button
                  onClick={() => setEditing(true)}
                  className="text-xs text-blue-600"
                >
                  Edit
                </button>
              ) : (
                <div className="flex gap-2">
                  <button
                    onClick={saveEdits}
                    className="text-xs px-2 py-1 bg-[var(--accent)] text-white rounded"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => {
                      setEditing(false);
                      setEditFields({});
                    }}
                    className="text-xs text-zinc-500"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
              {[
                ["invoice_number", "Invoice #", invoice.invoice_number],
                ["invoice_date", "Date", invoice.invoice_date],
                ["due_date", "Due Date", invoice.due_date],
                [
                  "supplier_name_extracted",
                  "Supplier",
                  invoice.supplier_name_extracted,
                ],
                ["subtotal", "Subtotal", invoice.subtotal],
                ["vat_rate", "VAT Rate", invoice.vat_rate],
                ["vat_amount", "VAT Amount", invoice.vat_amount],
                ["total_amount", "Total", invoice.total_amount],
                ["currency", "Currency", invoice.currency],
              ].map(([key, label, val]) => (
                <div key={key as string}>
                  <div className="text-xs text-zinc-500 mb-1">
                    {label as string}
                    {invoice.field_confidences?.[key as string] != null && (
                      <span
                        className={`ml-2 font-mono ${
                          (invoice.field_confidences[key as string] ?? 0) < 0.8
                            ? "text-orange-500"
                            : "text-green-500"
                        }`}
                      >
                        {(
                          (invoice.field_confidences[key as string] ?? 0) * 100
                        ).toFixed(0)}
                        %
                      </span>
                    )}
                  </div>
                  {editing ? (
                    <input
                      type="text"
                      defaultValue={String(val ?? "")}
                      onChange={(e) =>
                        setEditFields({
                          ...editFields,
                          [key as string]: e.target.value,
                        })
                      }
                      className="border border-[var(--border)] rounded px-2 py-1 text-sm w-full bg-white"
                    />
                  ) : (
                    <div className="font-mono">
                      {val != null ? String(val) : "—"}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Line items */}
          <div className="border border-[var(--border)] rounded-lg p-5">
            <h3 className="font-semibold text-sm mb-4">Line Items</h3>
            {invoice.line_items.length === 0 ? (
              <p className="text-sm text-zinc-400">No line items extracted</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-[var(--muted)]">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">
                      Description
                    </th>
                    <th className="text-right px-3 py-2 font-medium">Qty</th>
                    <th className="text-right px-3 py-2 font-medium">
                      Unit Price
                    </th>
                    <th className="text-right px-3 py-2 font-medium">
                      Amount
                    </th>
                    <th className="text-left px-3 py-2 font-medium">PO #</th>
                    <th className="text-left px-3 py-2 font-medium">
                      Material #
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.line_items.map((li) => (
                    <tr
                      key={li.id}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="px-3 py-2">{li.description || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono">
                        {li.quantity ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {li.unit_price ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {li.amount ?? "—"}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {li.po_number || "—"}
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {li.material_number || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Actions */}
          <div className="border border-[var(--border)] rounded-lg p-5">
            <h3 className="font-semibold text-sm mb-3">Actions</h3>
            <div className="space-y-2">
              {invoice.status === "received" && (
                <button
                  onClick={handleExtract}
                  className="w-full text-sm px-3 py-2 bg-blue-600 text-white rounded"
                >
                  Run OCR Extraction
                </button>
              )}
              {allowed.map((s) => (
                <button
                  key={s}
                  onClick={() => handleTransition(s)}
                  className="w-full text-sm px-3 py-2 bg-[var(--accent)] text-white rounded"
                >
                  Transition to {s}
                </button>
              ))}
            </div>
          </div>

          {/* Metadata */}
          <div className="border border-[var(--border)] rounded-lg p-5 text-xs space-y-2">
            <h3 className="font-semibold text-sm mb-3">Metadata</h3>
            <div className="flex justify-between">
              <span className="text-zinc-500">ID</span>
              <span className="font-mono">{invoice.id.slice(0, 12)}...</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">File</span>
              <span>{invoice.original_filename || invoice.file_url}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Type</span>
              <span>{invoice.file_type}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Created</span>
              <span>{new Date(invoice.created_at).toLocaleString()}</span>
            </div>
            {invoice.extracted_at && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Extracted</span>
                <span>
                  {new Date(invoice.extracted_at).toLocaleString()}
                </span>
              </div>
            )}
            {invoice.extraction_confidence != null && (
              <div className="flex justify-between">
                <span className="text-zinc-500">Confidence</span>
                <span className="font-mono">
                  {(invoice.extraction_confidence * 100).toFixed(0)}%
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
