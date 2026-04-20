"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";

interface Org {
  id: string;
  name: string;
}

interface ReconConfig {
  org_id: string;
  qty_tolerance_pct: number;
  price_tolerance_pct: number;
  auto_resolve_exact: boolean;
  ai_layer_enabled: boolean;
  ai_max_tokens_per_run: number;
}

export default function SettingsPage() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState("");
  const [newOrgName, setNewOrgName] = useState("");
  const [orgMsg, setOrgMsg] = useState("");
  const [config, setConfig] = useState<ReconConfig | null>(null);
  const [configMsg, setConfigMsg] = useState("");

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
    if (!orgId) return;
    fetch(`/api/v1/reconciliation/config?org_id=${orgId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setConfig(data))
      .catch(() => setConfig(null));
  }, [orgId]);

  async function createOrg() {
    if (!newOrgName.trim()) return;
    try {
      const res = await fetch("/api/v1/orgs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newOrgName.trim() }),
      });
      const data = await res.json();
      if (res.ok) {
        setOrgMsg(`Created: ${data.name}`);
        setNewOrgName("");
        // Reload
        const orgsRes = await fetch("/api/v1/orgs");
        const updated = await orgsRes.json();
        setOrgs(updated);
        setOrgId(data.id);
      } else {
        setOrgMsg(`Error: ${data.detail || JSON.stringify(data)}`);
      }
    } catch (e) {
      setOrgMsg(`Error: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function saveConfig() {
    if (!config || !orgId) return;
    try {
      const res = await fetch(`/api/v1/reconciliation/config?org_id=${orgId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          qty_tolerance_pct: config.qty_tolerance_pct,
          price_tolerance_pct: config.price_tolerance_pct,
          auto_resolve_exact: config.auto_resolve_exact,
          ai_layer_enabled: config.ai_layer_enabled,
          ai_max_tokens_per_run: config.ai_max_tokens_per_run,
        }),
      });
      if (res.ok) {
        setConfigMsg("Saved");
        setTimeout(() => setConfigMsg(""), 2000);
      } else {
        const err = await res.json();
        setConfigMsg(`Error: ${err.detail}`);
      }
    } catch {
      setConfigMsg("Save failed");
    }
  }

  return (
    <>
      <PageHeader
        title="Settings"
        description="Manage organizations and reconciliation configuration"
      />

      <div className="grid grid-cols-2 gap-6">
        {/* Organization Management */}
        <div className="border border-[var(--border)] rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-4">Organizations</h3>

          <div className="space-y-2 mb-4">
            {orgs.map((o) => (
              <div
                key={o.id}
                className={`flex items-center justify-between p-2 rounded text-sm ${
                  o.id === orgId ? "bg-[var(--muted)] font-medium" : ""
                }`}
              >
                <span
                  className="cursor-pointer"
                  onClick={() => setOrgId(o.id)}
                >
                  {o.name}
                </span>
                <span className="text-xs text-zinc-400 font-mono">
                  {o.id.slice(0, 8)}
                </span>
              </div>
            ))}
          </div>

          <hr className="border-[var(--border)] mb-4" />

          <label className="block text-xs font-medium mb-1">
            Create New Organization
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder="e.g. 梅州国威电子有限公司"
              className="flex-1 border border-[var(--border)] rounded px-3 py-2 text-sm bg-white"
            />
            <button
              onClick={createOrg}
              disabled={!newOrgName.trim()}
              className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm disabled:opacity-40"
            >
              Create
            </button>
          </div>
          {orgMsg && (
            <div className="mt-2 text-xs p-2 bg-[var(--muted)] rounded">
              {orgMsg}
            </div>
          )}
        </div>

        {/* Reconciliation Config */}
        <div className="border border-[var(--border)] rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-4">
            Reconciliation Config
          </h3>

          {config ? (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1">
                  Quantity Tolerance (%)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={config.qty_tolerance_pct}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      qty_tolerance_pct: parseFloat(e.target.value),
                    })
                  }
                  className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">
                  Price Tolerance (%)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={config.price_tolerance_pct}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      price_tolerance_pct: parseFloat(e.target.value),
                    })
                  }
                  className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.auto_resolve_exact}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      auto_resolve_exact: e.target.checked,
                    })
                  }
                />
                <label className="text-sm">Auto-resolve exact matches</label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.ai_layer_enabled}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      ai_layer_enabled: e.target.checked,
                    })
                  }
                />
                <label className="text-sm">AI matching layer enabled</label>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">
                  AI Max Tokens Per Run
                </label>
                <input
                  type="number"
                  value={config.ai_max_tokens_per_run}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      ai_max_tokens_per_run: parseInt(e.target.value),
                    })
                  }
                  className="border border-[var(--border)] rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>

              <button
                onClick={saveConfig}
                className="px-4 py-2 bg-[var(--accent)] text-white rounded text-sm"
              >
                Save Config
              </button>
              {configMsg && (
                <div className="text-xs text-zinc-500">{configMsg}</div>
              )}
            </div>
          ) : (
            <div className="text-sm text-zinc-400">
              {orgId
                ? "No config found for this org. Run a reconciliation first to auto-create defaults."
                : "Select an organization."}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
