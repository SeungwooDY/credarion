import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Auth gate. This is an *optimistic* check — it only looks for the presence of
 * the session cookie to decide routing. The cookie is signed and validated for
 * real by the backend on every API call (and on /auth/me), so a forged or
 * expired cookie still can't access data; it just won't be bounced here.
 *
 * (In Next.js 16, request middleware lives in `proxy.ts`, not `middleware.ts`.)
 */
const PUBLIC_PREFIXES = ["/login", "/landing"];
const SESSION_COOKIE = "credarion_session";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(p + "/"),
  );
  const hasSession = Boolean(request.cookies.get(SESSION_COOKIE)?.value);

  // Unauthenticated visitor hitting a protected page → send to login.
  if (!hasSession && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }

  // NOTE: we deliberately do NOT bounce cookie-holders away from /login.
  // The cookie check here is presence-only, so an expired/stale cookie (e.g.
  // after a failed logout while the backend was unreachable) would otherwise
  // cause a redirect loop: /login → / → API 401 → /login → … Landing on the
  // login page with a stale cookie is fine — signing in overwrites it.

  return NextResponse.next();
}

export const config = {
  // Run on every route except API (proxied to the backend), Next internals,
  // and static files (anything with a file extension).
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.).*)"],
};
