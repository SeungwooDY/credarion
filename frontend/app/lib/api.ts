/**
 * Lightweight API helper for the Credarion backend.
 * All requests go through the Next.js rewrite proxy (/api/* → localhost:8000/api/*).
 */

const API_BASE = "/api/v1";

/** Redirect to login on an expired/missing session (browser only). */
function handleUnauthorized() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  const next = encodeURIComponent(
    window.location.pathname + window.location.search,
  );
  window.location.assign(`/login?next=${next}`);
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...init?.headers,
    },
  });

  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("Not authenticated");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `API error ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export async function apiPost<T = unknown>(
  path: string,
  body?: unknown,
  init?: RequestInit
): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...init?.headers },
    body: body ? JSON.stringify(body) : undefined,
    ...init,
  });
}

export async function apiPut<T = unknown>(
  path: string,
  body?: unknown
): Promise<T> {
  return apiFetch<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function apiUpload<T = unknown>(
  path: string,
  formData: FormData
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  if (res.status === 401) {
    handleUnauthorized();
    throw new Error("Not authenticated");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Upload error ${res.status}`);
  }

  return res.json() as Promise<T>;
}
