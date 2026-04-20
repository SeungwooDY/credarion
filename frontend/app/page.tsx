"use client";

import { useEffect, useState } from "react";
import PageHeader from "./components/page-header";
import StatusBadge from "./components/status-badge";

interface Org {
  id: string;
  name: string;
  reporting_currency: string;
}

export default function DashboardPage() {
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [orgs, setOrgs] = useState<Org[]>([]);

  useEffect(() => {
    fetch("/api/v1/orgs")
      .then((r) => r.json())
      .then((data) => {
        setOrgs(data);
        setApiOk(true);
      })
      .catch(() => setApiOk(false));
  }, []);

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Overview of system status and quick links"
      />

      {/* Status cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div className="border border-[var(--border)] rounded-lg p-4">
          <div className="text-xs text-zinc-500 mb-1">API Status</div>
          <StatusBadge
            status={
              apiOk === null ? "running" : apiOk ? "success" : "error"
            }
          />
        </div>
        <div className="border border-[var(--border)] rounded-lg p-4">
          <div className="text-xs text-zinc-500 mb-1">Organizations</div>
          <div className="text-2xl font-semibold">{orgs.length}</div>
        </div>
        <div className="border border-[var(--border)] rounded-lg p-4">
          <div className="text-xs text-zinc-500 mb-1">Phase</div>
          <div className="text-sm font-medium">3 — Invoice Processing</div>
        </div>
      </div>

      {/* Quick Links */}
      <h3 className="text-sm font-semibold mb-3">Quick Actions</h3>
      <div className="grid grid-cols-2 gap-3 mb-8">
        <a
          href="/ingestion"
          className="border border-[var(--border)] rounded-lg p-4 hover:bg-[var(--muted)] transition-colors"
        >
          <div className="font-medium text-sm">Upload GRN / Statements</div>
          <div className="text-xs text-zinc-500 mt-1">
            Import ERP exports and supplier statements
          </div>
        </a>
        <a
          href="/reconciliation"
          className="border border-[var(--border)] rounded-lg p-4 hover:bg-[var(--muted)] transition-colors"
        >
          <div className="font-medium text-sm">Run Reconciliation</div>
          <div className="text-xs text-zinc-500 mt-1">
            4-layer matching engine
          </div>
        </a>
        <a
          href="/invoices"
          className="border border-[var(--border)] rounded-lg p-4 hover:bg-[var(--muted)] transition-colors"
        >
          <div className="font-medium text-sm">Process Invoices</div>
          <div className="text-xs text-zinc-500 mt-1">
            Upload fapiao for OCR extraction
          </div>
        </a>
        <a
          href="/settings"
          className="border border-[var(--border)] rounded-lg p-4 hover:bg-[var(--muted)] transition-colors"
        >
          <div className="font-medium text-sm">Settings</div>
          <div className="text-xs text-zinc-500 mt-1">
            Organization and reconciliation config
          </div>
        </a>
      </div>

      {/* Organizations table */}
      {orgs.length > 0 && (
        <>
          <h3 className="text-sm font-semibold mb-3">Organizations</h3>
          <table className="w-full text-sm border border-[var(--border)] rounded-lg overflow-hidden">
            <thead className="bg-[var(--muted)]">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Name</th>
                <th className="text-left px-4 py-2 font-medium">Currency</th>
                <th className="text-left px-4 py-2 font-medium">ID</th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2">{org.name}</td>
                  <td className="px-4 py-2">{org.reporting_currency}</td>
                  <td className="px-4 py-2 font-mono text-xs text-zinc-400">
                    {org.id.slice(0, 8)}...
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
