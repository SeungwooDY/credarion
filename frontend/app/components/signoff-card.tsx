"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Lock, LockOpen } from "lucide-react";
import { PeriodBadge } from "@/app/components/period-switcher";
import { CARD } from "@/app/lib/ui";
import { usePeriod } from "@/app/lib/period";
import { useT } from "@/app/lib/i18n";
import {
  useCurrentOrg,
  useEscalations,
  useIsAdmin,
  useSignoff,
  useSuppliers,
} from "@/app/lib/swr";

/**
 * Dashboard month-end sign-off card for the GLOBALLY selected period (the
 * sidebar switcher is the single period control).
 *
 * Everyone sees the lock state; only admins get the Sign off / Reopen
 * actions. Signing off locks the period (mutating endpoints return 423
 * until an admin reopens).
 */
export default function SignoffCard() {
  const t = useT();
  const { mutate } = useSWRConfig();
  const { orgId } = useCurrentOrg();
  const isAdmin = useIsAdmin();
  const { period } = usePeriod();
  const { locked, signoff, refreshSignoff } = useSignoff(orgId, period);
  const [confirming, setConfirming] = useState<"sign" | "reopen" | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  // Readiness summary — fetched only while the sign-off confirmation is open,
  // so the admin sees exactly what state they're about to lock.
  const signing = confirming === "sign";
  const { suppliers } = useSuppliers(signing ? orgId : "", period);
  const { escalations } = useEscalations(signing ? orgId : "", { period });
  const pendingReview = suppliers.reduce((n, s) => n + s.pending_review, 0);
  const unmatched = suppliers.reduce((n, s) => n + s.unmatched, 0);
  const notReady = suppliers.filter((s) => !s.ready).length;
  const openEscalations = escalations.filter((e) => e.status !== "resolved").length;
  const issueCount = pendingReview + unmatched + notReady + openEscalations;

  async function submit() {
    if (!confirming) return;
    setBusy(true);
    try {
      await fetch(
        confirming === "sign" ? "/api/v1/signoffs" : "/api/v1/signoffs/reopen",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            org_id: orgId,
            period,
            note: note.trim() || undefined,
          }),
        }
      );
      refreshSignoff();
      // The sidebar switcher's period list caches lock flags — invalidate it
      // so the lock icon appears/disappears immediately after sign-off/reopen.
      mutate(`/periods?org_id=${orgId}`);
    } catch {
      // state refresh will reflect reality
    }
    setBusy(false);
    setConfirming(null);
    setNote("");
  }

  const signedDate = signoff?.signed_off_at
    ? new Date(signoff.signed_off_at).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : "";

  return (
    <div className={`${CARD} mt-6 p-4`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {locked ? (
            <Lock className="h-4 w-4 text-emerald-600" />
          ) : (
            <LockOpen className="h-4 w-4 text-zinc-400" />
          )}
          <div>
            <h3 className="text-sm font-semibold text-gray-800">
              {t("signoff.card_title")}
            </h3>
            <p className="text-xs text-zinc-500">
              {locked
                ? t("signoff.signed_off_by", {
                    name: signoff?.signed_off_by_name ?? "—",
                    date: signedDate,
                  })
                : t("signoff.card_hint")}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <PeriodBadge />
          {locked ? (
            <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
              {t("signoff.signed_off")}
            </span>
          ) : (
            <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-zinc-500">
              {t("signoff.not_signed_off")}
            </span>
          )}
          {isAdmin &&
            (locked ? (
              <button
                onClick={() => setConfirming("reopen")}
                className="px-3 py-1.5 text-xs font-medium border border-border rounded-lg hover:bg-muted transition-colors"
              >
                {t("signoff.reopen")}
              </button>
            ) : (
              <button
                onClick={() => setConfirming("sign")}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-accent text-white hover:opacity-90 transition-opacity"
              >
                {t("signoff.sign_off", { period })}
              </button>
            ))}
        </div>
      </div>

      {locked && signoff?.note && (
        <p className="mt-2 text-xs text-zinc-500 pl-6">“{signoff.note}”</p>
      )}

      {/* Portaled to <body>: the dashboard root is animated (transformed), which
          would otherwise make position:fixed center on the page, not the viewport. */}
      {confirming &&
        createPortal(
          <div
            className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
            onClick={() => setConfirming(null)}
          >
            <div
              className="bg-card rounded-2xl shadow-xl w-full max-w-md p-5"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="font-semibold text-sm mb-3">
                {confirming === "sign"
                  ? t("signoff.sign_off", { period })
                  : `${t("signoff.reopen")} — ${period}`}
              </h3>

              {/* Readiness summary — what you're about to lock */}
              {signing &&
                (issueCount > 0 ? (
                  <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-800">
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      {t("signoff.outstanding", { n: issueCount })}
                    </div>
                    <ul className="mt-1.5 space-y-0.5 pl-5 text-xs text-amber-800">
                      {pendingReview > 0 && (
                        <li>{t("signoff.pending_review", { n: pendingReview })}</li>
                      )}
                      {unmatched > 0 && (
                        <li>{t("signoff.unmatched_lines", { n: unmatched })}</li>
                      )}
                      {notReady > 0 && (
                        <li>{t("signoff.suppliers_not_ready", { n: notReady })}</li>
                      )}
                      {openEscalations > 0 && (
                        <li>{t("signoff.open_escalations", { n: openEscalations })}</li>
                      )}
                    </ul>
                    <p className="mt-1.5 pl-5 text-xs text-amber-700">
                      {t("signoff.outstanding_hint")}
                    </p>
                  </div>
                ) : (
                  <div className="mb-3 flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs font-medium text-emerald-800">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    {t("signoff.all_clear")}
                  </div>
                ))}

              <label className="block text-xs font-medium text-zinc-500 mb-1">
                {t("signoff.note")}
              </label>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("signoff.note_placeholder")}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm h-20 resize-none focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent"
              />
              <div className="flex gap-2 mt-4 justify-end">
                <button
                  onClick={() => setConfirming(null)}
                  className="px-3 py-1.5 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
                >
                  {t("common.cancel")}
                </button>
                <button
                  onClick={submit}
                  disabled={busy}
                  className={`px-3 py-1.5 text-xs rounded-lg text-white hover:opacity-90 disabled:opacity-50 transition-opacity ${
                    signing && issueCount > 0 ? "bg-amber-600" : "bg-accent"
                  }`}
                >
                  {signing
                    ? issueCount > 0
                      ? t("signoff.confirm_anyway")
                      : t("signoff.confirm")
                    : t("signoff.confirm_reopen")}
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
