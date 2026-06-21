"use client";

import { useEffect, useState } from "react";
import PageHeader from "../components/page-header";
import { useOrgs, useReconConfig } from "../lib/swr";
import { CARD } from "@/app/lib/ui";
import { useT } from "@/app/lib/i18n";

interface ReconConfigForm {
  qty_tolerance_pct: number;
  price_tolerance_pct: number;
  auto_resolve_exact: boolean;
  ai_layer_enabled: boolean;
  ai_max_tokens_per_run: number;
}

export default function SettingsPage() {
  const t = useT();
  const { orgs, refreshOrgs } = useOrgs();
  const [orgId, setOrgId] = useState("");
  const [newOrgName, setNewOrgName] = useState("");
  const [orgMsg, setOrgMsg] = useState("");
  const { config, refreshConfig } = useReconConfig(orgId);
  const [formConfig, setFormConfig] = useState<ReconConfigForm | null>(null);
  const [configMsg, setConfigMsg] = useState("");

  useEffect(() => {
    if (orgs.length > 0 && !orgId) setOrgId(orgs[0].id);
  }, [orgs, orgId]);

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
        setOrgMsg(t("settings.created_msg", { name: data.name }));
        setNewOrgName("");
        await refreshOrgs();
        setOrgId(data.id);
      } else {
        setOrgMsg(
          t("settings.error_msg", {
            detail: data.detail || JSON.stringify(data),
          })
        );
      }
    } catch (e) {
      setOrgMsg(
        t("settings.error_msg", {
          detail: e instanceof Error ? e.message : String(e),
        })
      );
    }
  }

  async function saveConfig() {
    if (!formConfig || !orgId) return;
    try {
      const res = await fetch(`/api/v1/reconciliation/config?org_id=${orgId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formConfig),
      });
      if (res.ok) {
        setConfigMsg(t("settings.saved"));
        refreshConfig();
        setTimeout(() => setConfigMsg(""), 2000);
      } else {
        const err = await res.json();
        setConfigMsg(t("settings.error_msg", { detail: err.detail }));
      }
    } catch {
      setConfigMsg(t("settings.save_failed"));
    }
  }

  return (
    <>
      <PageHeader
        title={t("settings.title")}
        description={t("settings.description")}
      />

      <div className="grid grid-cols-2 gap-6">
        {/* Organization Management */}
        <div className={`${CARD} p-5`}>
          <h3 className="font-semibold text-sm mb-4">{t("settings.organizations")}</h3>

          <div className="space-y-2 mb-4">
            {orgs.map((o) => (
              <div
                key={o.id}
                className={`flex items-center justify-between p-2 rounded text-sm ${
                  o.id === orgId ? "bg-muted font-medium" : ""
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

          <hr className="border-border mb-4" />

          <label className="block text-xs font-medium mb-1">
            {t("settings.create_new_org")}
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder={t("settings.org_name_placeholder")}
              className="flex-1 border border-border rounded px-3 py-2 text-sm bg-white"
            />
            <button
              onClick={createOrg}
              disabled={!newOrgName.trim()}
              className="px-4 py-2 bg-accent text-white rounded text-sm disabled:opacity-40"
            >
              {t("settings.create")}
            </button>
          </div>
          {orgMsg && (
            <div className="mt-2 text-xs p-2 bg-muted rounded">
              {orgMsg}
            </div>
          )}
        </div>

        {/* Reconciliation Config */}
        <div className={`${CARD} p-5`}>
          <h3 className="font-semibold text-sm mb-4">
            {t("settings.recon_config")}
          </h3>

          {formConfig ? (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1">
                  {t("settings.qty_tolerance")}
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
                  {t("settings.price_tolerance")}
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
                <label className="text-sm">{t("settings.auto_resolve_exact")}</label>
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
                <label className="text-sm">{t("settings.ai_layer_enabled")}</label>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">
                  {t("settings.ai_max_tokens")}
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
                {t("settings.save_config")}
              </button>
              {configMsg && (
                <div className="text-xs text-zinc-500">{configMsg}</div>
              )}
            </div>
          ) : (
            <div className="text-sm text-zinc-400">
              {orgId
                ? t("settings.no_config")
                : t("settings.select_org")}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
