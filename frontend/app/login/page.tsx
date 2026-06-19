"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

function LoginForm() {
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(
          body.detail ||
            (res.status === 401
              ? "Invalid email or password"
              : "Unable to sign in. Please try again."),
        );
        setSubmitting(false);
        return;
      }

      // Cookie is set; do a full navigation so the proxy re-evaluates auth.
      const safeNext = nextPath.startsWith("/") ? nextPath : "/";
      window.location.assign(safeNext);
    } catch {
      setError("Network error. Please check your connection and try again.");
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div className="space-y-1.5">
        <label htmlFor="email" className="block text-sm font-medium text-zinc-700">
          Work email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
          className="w-full rounded-xl border border-border bg-white px-3.5 py-2.5 text-sm text-zinc-800 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="password" className="block text-sm font-medium text-zinc-700">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="••••••••"
          className="w-full rounded-xl border border-border bg-white px-3.5 py-2.5 text-sm text-zinc-800 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
        />
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 px-3.5 py-2.5 text-sm text-red-600 border border-red-100">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark px-4 py-2.5 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(108,60,224,0.35)] transition hover:shadow-[0_6px_20px_rgba(108,60,224,0.45)] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {submitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen w-full bg-background flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark text-sm font-bold text-white">
            C
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-foreground">
              Credarion
            </h1>
            <p className="text-[10px] uppercase leading-none tracking-wide text-zinc-400">
              Accounting Co-pilot
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-border bg-card p-7 shadow-[0_4px_24px_rgba(26,26,46,0.06)]">
          <h2 className="text-lg font-semibold text-zinc-800">Welcome back</h2>
          <p className="mb-6 mt-1 text-sm text-zinc-500">
            Sign in to your account to continue.
          </p>

          <Suspense fallback={null}>
            <LoginForm />
          </Suspense>
        </div>

        <p className="mt-6 text-center text-xs text-zinc-400">
          Trouble signing in? Contact your account manager.
        </p>
      </div>
    </div>
  );
}
