"use client";

import { useState } from "react";
import { CARD } from "@/app/lib/ui";
import { useT } from "@/app/lib/i18n";
import {
  useIsAdmin,
  useMe,
  useTeam,
  type TeamMember,
} from "@/app/lib/swr";

const ROLE_CHIP: Record<TeamMember["role"], string> = {
  admin: "bg-purple-50 text-purple-700 border-purple-200",
  accountant: "bg-blue-50 text-blue-700 border-blue-200",
};

function AddUserModal({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: () => void;
}) {
  const t = useT();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<"admin" | "accountant">("accountant");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const valid = email.includes("@") && password.length >= 8;

  async function handleSubmit() {
    if (!valid) return;
    setSubmitting(true);
    setError("");
    try {
      const res = await fetch("/api/v1/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          email: email.trim(),
          password,
          full_name: fullName.trim() || undefined,
          role,
        }),
      });
      if (res.ok) {
        onAdded();
        onClose();
      } else {
        const body = await res.json().catch(() => ({}));
        setError(body.detail || t("team.add_failed"));
      }
    } catch {
      setError(t("team.add_failed"));
    }
    setSubmitting(false);
  }

  const input =
    "w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent";

  return (
    <div
      className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-card rounded-2xl shadow-xl w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-semibold text-sm mb-3">{t("team.add_user")}</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">
              {t("team.email")}
            </label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} />
          </div>
          <div>
            <label className="block text-xs font-medium text-zinc-500 mb-1">
              {t("team.full_name")}
            </label>
            <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} className={input} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1">
                {t("team.role")}
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as "admin" | "accountant")}
                className={input}
              >
                <option value="accountant">{t("team.role.accountant")}</option>
                <option value="admin">{t("team.role.admin")}</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-zinc-500 mb-1">
                {t("team.temp_password")}
              </label>
              <input
                type="text"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("team.temp_password_hint")}
                className={input}
              />
            </div>
          </div>
          <p className="text-xs text-zinc-400">{t("team.share_hint")}</p>
          {error && <p className="text-xs text-red-600">{error}</p>}
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
            disabled={submitting || !valid}
            className="px-3 py-1.5 text-xs rounded-lg bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {t("team.add_user")}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Admin-only team table: add users, flip roles, deactivate/reactivate. */
export function TeamSettings() {
  const t = useT();
  const isAdmin = useIsAdmin();
  const { me } = useMe();
  const { team, teamLoading, refreshTeam } = useTeam(isAdmin);
  const [showAdd, setShowAdd] = useState(false);
  const [error, setError] = useState("");

  if (!isAdmin) return null;

  async function patchUser(id: string, body: { role?: string; is_active?: boolean }) {
    setError("");
    const res = await fetch(`/api/v1/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || t("team.update_failed"));
    }
    refreshTeam();
  }

  return (
    <div className={`${CARD} p-5 mt-6`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-sm">{t("team.title")}</h3>
          <p className="text-xs text-zinc-400">{t("team.subtitle")}</p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="px-3 py-1.5 text-xs font-medium rounded-lg bg-accent text-white hover:opacity-90 transition-opacity"
        >
          {t("team.add_user")}
        </button>
      </div>

      {error && (
        <p className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {teamLoading ? (
        <div className="text-sm text-zinc-400">{t("common.loading")}</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs text-zinc-400 uppercase tracking-wider">
              <th className="text-left py-2 font-medium">{t("team.member")}</th>
              <th className="text-left py-2 font-medium">{t("team.role")}</th>
              <th className="text-left py-2 font-medium">{t("team.status")}</th>
              <th className="text-right py-2 font-medium">{t("team.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {team.map((u) => {
              const isSelf = u.id === me?.id;
              return (
                <tr key={u.id} className="border-b border-border last:border-b-0">
                  <td className="py-2.5">
                    <div className="font-medium text-foreground">
                      {u.full_name || u.email}
                      {isSelf && (
                        <span className="ml-1.5 text-xs text-zinc-400">
                          ({t("team.you")})
                        </span>
                      )}
                    </div>
                    {u.full_name && (
                      <div className="text-xs text-zinc-400">{u.email}</div>
                    )}
                  </td>
                  <td className="py-2.5">
                    <span
                      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${ROLE_CHIP[u.role]}`}
                    >
                      {t(`team.role.${u.role}`)}
                    </span>
                  </td>
                  <td className="py-2.5">
                    <span
                      className={`text-xs font-medium ${u.is_active ? "text-emerald-600" : "text-zinc-400"}`}
                    >
                      {u.is_active ? t("team.active") : t("team.deactivated")}
                    </span>
                  </td>
                  <td className="py-2.5 text-right">
                    {!isSelf && !u.is_superuser && (
                      <div className="inline-flex gap-2">
                        <button
                          onClick={() =>
                            patchUser(u.id, {
                              role: u.role === "admin" ? "accountant" : "admin",
                            })
                          }
                          className="px-2.5 py-1 text-xs border border-border rounded-lg hover:bg-muted transition-colors"
                        >
                          {u.role === "admin"
                            ? t("team.make_accountant")
                            : t("team.make_admin")}
                        </button>
                        <button
                          onClick={() => patchUser(u.id, { is_active: !u.is_active })}
                          className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                            u.is_active
                              ? "border-red-200 text-red-600 hover:bg-red-50"
                              : "border-emerald-200 text-emerald-600 hover:bg-emerald-50"
                          }`}
                        >
                          {u.is_active ? t("team.deactivate") : t("team.reactivate")}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {showAdd && (
        <AddUserModal onClose={() => setShowAdd(false)} onAdded={refreshTeam} />
      )}
    </div>
  );
}

/** Change-password form for the logged-in user (any role). */
export function PasswordSettings() {
  const t = useT();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!current || next.length < 8) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/v1/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      if (res.ok) {
        setMsg({ ok: true, text: t("team.password_changed") });
        setCurrent("");
        setNext("");
      } else {
        const data = await res.json().catch(() => ({}));
        setMsg({ ok: false, text: data.detail || t("team.password_change_failed") });
      }
    } catch {
      setMsg({ ok: false, text: t("team.password_change_failed") });
    }
    setBusy(false);
  }

  const input =
    "w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent";

  return (
    <div className={`${CARD} p-5 mt-6`}>
      <h3 className="font-semibold text-sm mb-4">{t("team.change_password")}</h3>
      <div className="grid grid-cols-2 gap-3 max-w-xl">
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">
            {t("team.current_password")}
          </label>
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={input}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">
            {t("team.new_password")}
          </label>
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            placeholder={t("team.temp_password_hint")}
            className={input}
          />
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={submit}
          disabled={busy || !current || next.length < 8}
          className="px-4 py-2 bg-accent text-white rounded text-sm disabled:opacity-50"
        >
          {t("team.change_password")}
        </button>
        {msg && (
          <span className={`text-xs ${msg.ok ? "text-emerald-600" : "text-red-600"}`}>
            {msg.text}
          </span>
        )}
      </div>
    </div>
  );
}
