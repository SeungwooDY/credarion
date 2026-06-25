"use client";

/**
 * Global month switcher shown at the top of every product page.
 *
 * - A scrollable tab strip of the active org's accounting periods (newest first).
 * - A "+ New month" control that creates the next period and switches to it.
 * - An org dropdown (only when the account has more than one org).
 *
 * Reads/writes the active org + period via useOrgPeriod, and owns the "smart
 * defaulting": pick the first org and newest month when nothing is selected yet.
 */
import { useEffect, useState } from "react";

import { apiPost } from "@/app/lib/api";
import { useOrgPeriod } from "@/app/lib/period";
import { type AccountingPeriod, useOrgs, usePeriods } from "@/app/lib/swr";

/** Next month after the newest existing period, or the current month if none. */
function defaultNewPeriod(periods: AccountingPeriod[]): string {
  if (periods.length > 0) {
    const latest = periods[0].period; // list is newest-first
    let year = Number(latest.slice(0, 4));
    let month = Number(latest.slice(5, 7)) + 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
    return `${year}-${String(month).padStart(2, "0")}`;
  }
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const TAB_BASE =
  "shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap";

export default function PeriodBar() {
  const { orgs } = useOrgs();
  const { orgId, period, setOrgId, setPeriod } = useOrgPeriod();
  const { periods, refreshPeriods } = usePeriods(orgId);

  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Default the org to the first one once orgs load.
  useEffect(() => {
    if (orgs.length > 0 && !orgId) setOrgId(orgs[0].id);
  }, [orgs, orgId, setOrgId]);

  // Default / reconcile the period: if nothing is selected, or the selected
  // month isn't one of this org's periods, jump to the newest.
  useEffect(() => {
    if (periods.length === 0) return;
    if (!period || !periods.some((p) => p.period === period)) {
      setPeriod(periods[0].period);
    }
  }, [periods, period, setPeriod]);

  async function handleCreate() {
    if (!orgId || !draft) return;
    setBusy(true);
    setError("");
    try {
      await apiPost("/periods", { org_id: orgId, period: draft });
      await refreshPeriods();
      setPeriod(draft);
      setCreating(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(false);
  }

  // Nothing to show until we know the org.
  if (orgs.length === 0) return null;

  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 border-b border-border pb-4">
      {orgs.length > 1 && (
        <select
          value={orgId}
          onChange={(e) => setOrgId(e.target.value)}
          className="shrink-0 rounded-lg border border-border bg-card px-3 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      )}

      <div className="flex items-center gap-1 overflow-x-auto">
        {periods.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setPeriod(p.period)}
            className={`${TAB_BASE} ${
              p.period === period
                ? "bg-accent text-white"
                : "border border-border bg-card text-zinc-600 hover:bg-muted"
            }`}
            title={p.status === "closed" ? "Closed" : "Open"}
          >
            {p.label}
          </button>
        ))}
        {periods.length === 0 && (
          <span className="text-sm text-zinc-400">No months yet — create one →</span>
        )}
      </div>

      {creating ? (
        <div className="flex shrink-0 items-center gap-2">
          <input
            type="month"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          />
          <button
            type="button"
            onClick={handleCreate}
            disabled={busy || !draft}
            className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create"}
          </button>
          <button
            type="button"
            onClick={() => {
              setCreating(false);
              setError("");
            }}
            className="rounded-lg px-2 py-1.5 text-sm text-zinc-500 hover:text-zinc-700"
          >
            Cancel
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => {
            setDraft(defaultNewPeriod(periods));
            setCreating(true);
            setError("");
          }}
          className="shrink-0 rounded-lg border border-dashed border-border px-3 py-1.5 text-sm font-medium text-accent hover:bg-accent-light"
        >
          + New month
        </button>
      )}

      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  );
}
