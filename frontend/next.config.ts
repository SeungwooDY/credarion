import type { NextConfig } from "next";

// Backend origin the /api/* requests are proxied to. Set BACKEND_URL in
// production (e.g. the Render backend service URL); falls back to the local
// uvicorn dev server when unset.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Hide the dev-only on-screen route/bundler indicator; it sat bottom-left and
  // overlapped the language toggle. Build/runtime errors are still surfaced.
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
