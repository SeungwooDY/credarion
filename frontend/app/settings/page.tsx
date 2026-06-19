"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import { useCurrentOrg, useReconConfig } from "../lib/swr";

interface ReconConfigForm {
  qty_tolerance_pct: number;
  price_tolerance_pct: number;
  auto_resolve_exact: boolean;
  ai_layer_enabled: boolean;
  ai_max_tokens_per_run: number;
}

export default function SettingsPage() {
  const { orgId, orgName } = useCurrentOrg();
  const { config, refreshConfig } = useReconConfig(orgId);
  const [formConfig, setFormConfig] = useState<ReconConfigForm | null>(null);
  const [configMsg, setConfigMsg] = useState("");

  // Sync SWR config into local form state
  useEffect(() => {
    if (config) {
      setFormConfig({
        qty_tolerance_pct: config.qty_tolerance_pct,
        price_tolerance_pct: config.price_tolerance_pct,
        auto_resolve_exact: config.auto_resolve_exact,
        ai_layer_enabled: config.ai_layer_enabled,
        ai_max_tokens_per_run: config.ai_max_tokens_per_run,
      });
    } else {
      setFormConfig(null);
    }
  }, [config]);

  async function saveConfig() {
    if (!formConfig || !orgId) return;
    try {
      const res = await fetch(`/api/v1/reconciliation/config?org_id=${orgId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formConfig),
      });
      if (res.ok) {
        setConfigMsg("Saved");
        refreshConfig();
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
        description="Your organization and reconciliation configuration"
      />

      <div className="grid grid-cols-2 gap-6">
        {/* Organization */}
        <div className="border border-border rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-4">Organization</h3>
          {orgId ? (
            <div className="flex items-center justify-between p-2 rounded text-sm bg-muted font-medium">
              <span>{orgName}</span>
              <span className="text-xs text-zinc-400 font-mono">
                {orgId.slice(0, 8)}
              </span>
            </div>
          ) : (
            <div className="text-sm text-zinc-400">
              No organization is linked to your account yet.
            </div>
          )}
        </div>

        {/* Reconciliation Config */}
        <div className="border border-border rounded-lg p-5">
          <h3 className="font-semibold text-sm mb-4">
            Reconciliation Config
          </h3>

          {formConfig ? (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1">
                  Quantity Tolerance (%)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={formConfig.qty_tolerance_pct}
                  onChange={(e) =>
                    setFormConfig({
                      ...formConfig,
                      qty_tolerance_pct: parseFloat(e.target.value),
                    })
                  }
                  className="border border-border rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">
                  Price Tolerance (%)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={formConfig.price_tolerance_pct}
                  onChange={(e) =>
                    setFormConfig({
                      ...formConfig,
                      price_tolerance_pct: parseFloat(e.target.value),
                    })
                  }
                  className="border border-border rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={formConfig.auto_resolve_exact}
                  onChange={(e) =>
                    setFormConfig({
                      ...formConfig,
                      auto_resolve_exact: e.target.checked,
                    })
                  }
                />
                <label className="text-sm">Auto-resolve exact matches</label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={formConfig.ai_layer_enabled}
                  onChange={(e) =>
                    setFormConfig({
                      ...formConfig,
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
                  value={formConfig.ai_max_tokens_per_run}
                  onChange={(e) =>
                    setFormConfig({
                      ...formConfig,
                      ai_max_tokens_per_run: parseInt(e.target.value),
                    })
                  }
                  className="border border-border rounded px-3 py-2 text-sm w-full bg-white"
                />
              </div>

              <button
                onClick={saveConfig}
                className="px-4 py-2 bg-accent text-white rounded text-sm"
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
                : "No organization is linked to your account yet."}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
