"use client";

import { useState } from "react";
import PageHeader from "../components/page-header";
import {
  useCurrentOrg,
  useEscalations,
  useIsAdmin,
  type EscalationItem,
} from "../lib/swr";
import { CARD } from "@/app/lib/ui";
import { useT } from "@/app/lib/i18n";

const STATUS_STYLES: Record<EscalationItem["status"], string> = {
  open: "bg-red-50 text-red-700 border-red-200",
  acknowledged: "bg-amber-50 text-amber-700 border-amber-200",
  resolved: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

function StatusChip({ status }: { status: EscalationItem["status"] }) {
  const t = useT();
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {t(`esc.status.${status}`)}
    </span>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/** Free-form "Raise issue" modal (org+period+title+description). */
function RaiseModal({
  orgId,
  onClose,
  onRaised,
}: {
  orgId: string;
  onClose: () => void;
  onRaised: () => void;
}) {
  const t = useT();
  const now = new Date();
  const defaultPeriod = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [period, setPeriod] = useState(defaultPeriod);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!title.trim()) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/v1/escalations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          org_id: orgId,
          period,
          title: title.trim(),
          description: description.trim() || undefined,
        }),
      });
      if (res.ok) onRaised();
    } catch {
      // surfaced via list refresh; keep the modal simple
    }
    setSubmitting(false);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-card rounded-2xl shadow-xl w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-sm mb-3">{t("esc.raise")}</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">
              {t("esc.form.title")}
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={t("esc.form.title_placeholder")}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">
              {t("esc.form.period")}
            </label>
            <input
              type="month"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">
              {t("esc.form.description")}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t("esc.form.description_placeholder")}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
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
          <button
            onClick={handleSubmit}
            disabled={submitting || !title.trim()}
            className="px-3 py-1.5 text-xs rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {t("esc.form.submit")}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Admin resolve modal with the required note. */
function ResolveModal({
  escalation,
  onClose,
  onResolved,
}: {
  escalation: EscalationItem;
  onClose: () => void;
  onResolved: () => void;
}) {
  const t = useT();
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleResolve() {
    if (!note.trim()) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/v1/escalations/${escalation.id}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ resolution_note: note.trim() }),
      });
      if (res.ok) onResolved();
    } catch {
      // list refresh will reflect reality
    }
    setSubmitting(false);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-card rounded-2xl shadow-xl w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-sm mb-1">{t("esc.resolve")}</h3>
        <p className="text-xs text-zinc-500 mb-3">{escalation.title}</p>
        <label className="block text-xs font-medium text-zinc-500 mb-1">
          {t("esc.resolution_note")}
        </label>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={t("esc.resolution_note_placeholder")}
          className="w-full border border-border rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
        />
        <div className="flex gap-2 mt-4 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
          >
            {t("common.cancel")}
          </button>
          <button
            onClick={handleResolve}
            disabled={submitting || !note.trim()}
            className="px-3 py-1.5 text-xs rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {t("esc.resolve")}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function EscalationsPage() {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const isAdmin = useIsAdmin();
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { escalations, escalationsLoading, refreshEscalations } = useEscalations(
    orgId,
    statusFilter ? { status: statusFilter } : undefined
  );
  const [showRaise, setShowRaise] = useState(false);
  const [resolveTarget, setResolveTarget] = useState<EscalationItem | null>(null);

  async function acknowledge(id: string) {
    await fetch(`/api/v1/escalations/${id}/acknowledge`, {
      method: "POST",
      credentials: "include",
    });
    refreshEscalations();
  }

  return (
    <div className="space-y-6">
      <PageHeader title={t("esc.title")} description={t("esc.subtitle")} />

      <div className="flex items-center justify-between gap-3">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-border rounded-lg px-3 py-1.5 text-sm bg-card focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          <option value="">{t("esc.filter.all")}</option>
          <option value="open">{t("esc.status.open")}</option>
          <option value="acknowledged">{t("esc.status.acknowledged")}</option>
          <option value="resolved">{t("esc.status.resolved")}</option>
        </select>
        <button
          onClick={() => setShowRaise(true)}
          className="px-3 py-1.5 text-sm rounded-lg bg-accent text-white hover:opacity-90 transition-opacity"
        >
          {t("esc.raise")}
        </button>
      </div>

      <div className={CARD}>
        {escalationsLoading ? (
          <div className="p-6 text-sm text-zinc-400">{t("common.loading")}</div>
        ) : escalations.length === 0 ? (
          <div className="p-8 text-center text-sm text-zinc-400">{t("esc.empty")}</div>
        ) : (
          <ul className="divide-y divide-border">
            {escalations.map((e) => (
              <li key={e.id} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <StatusChip status={e.status} />
                      <span className="text-sm font-medium text-foreground">
                        {e.title}
                      </span>
                      <span className="text-xs text-zinc-400">{e.period}</span>
                    </div>
                    {e.description && (
                      <p className="mt-1 text-xs text-zinc-500">{e.description}</p>
                    )}
                    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-zinc-400">
                      {e.raised_by_name && (
                        <span>
                          {t("esc.raised_by", { name: e.raised_by_name })} ·{" "}
                          {fmtDate(e.created_at)}
                        </span>
                      )}
                      {e.supplier_name && (
                        <span>
                          {t("esc.supplier")}: {e.supplier_name}
                        </span>
                      )}
                      {e.result_id && <span>{t("esc.linked_line")}</span>}
                      {e.acknowledged_by_name && (
                        <span>
                          {t("esc.acknowledged_by", { name: e.acknowledged_by_name })}{" "}
                          · {fmtDate(e.acknowledged_at)}
                        </span>
                      )}
                    </div>
                    {e.status === "resolved" && e.resolution_note && (
                      <p className="mt-2 rounded-lg bg-emerald-50 border border-emerald-100 px-2.5 py-1.5 text-xs text-emerald-800">
                        {t("esc.resolved_by", { name: e.resolved_by_name ?? "—" })}{" "}
                        · {fmtDate(e.resolved_at)} — {e.resolution_note}
                      </p>
                    )}
                  </div>
                  {isAdmin && e.status !== "resolved" && (
                    <div className="flex shrink-0 gap-2">
                      {e.status === "open" && (
                        <button
                          onClick={() => acknowledge(e.id)}
                          className="px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
                        >
                          {t("esc.acknowledge")}
                        </button>
                      )}
                      <button
                        onClick={() => setResolveTarget(e)}
                        className="px-2.5 py-1 text-xs rounded-lg bg-accent text-white hover:opacity-90 transition-opacity"
                      >
                        {t("esc.resolve")}
                      </button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {showRaise && (
        <RaiseModal
          orgId={orgId}
          onClose={() => setShowRaise(false)}
          onRaised={refreshEscalations}
        />
      )}
      {resolveTarget && (
        <ResolveModal
          escalation={resolveTarget}
          onClose={() => setResolveTarget(null)}
          onResolved={refreshEscalations}
        />
      )}
    </div>
  );
}
