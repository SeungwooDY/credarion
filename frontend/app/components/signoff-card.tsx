"use client";

import { useState } from "react";
import { Lock, LockOpen } from "lucide-react";
import { MonthPicker } from "@/components/ui/month-picker";
import { CARD } from "@/app/lib/ui";
import { useT } from "@/app/lib/i18n";
import { useCurrentOrg, useIsAdmin, useSignoff } from "@/app/lib/swr";

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Dashboard month-end sign-off card.
 *
 * Everyone sees the lock state for the picked period; only admins get the
 * Sign off / Reopen actions. Signing off locks the period (mutating endpoints
 * return 423 until an admin reopens).
 */
export default function SignoffCard() {
  const t = useT();
  const { orgId } = useCurrentOrg();
  const isAdmin = useIsAdmin();
  const [period, setPeriod] = useState(currentPeriod());
  const { locked, signoff, refreshSignoff } = useSignoff(orgId, period);
  const [confirming, setConfirming] = useState<"sign" | "reopen" | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

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
          <MonthPicker value={period} onChange={setPeriod} label={t("common.period")} />
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

      {confirming && (
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
                className="px-3 py-1.5 text-xs rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {confirming === "sign"
                  ? t("signoff.confirm")
                  : t("signoff.confirm_reopen")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
