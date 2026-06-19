import type { NextConfig } from "next";

// Backend origin the /api/* requests are proxied to. Set BACKEND_URL in
// production (e.g. the Railway backend service URL); falls back to the local
// uvicorn dev server when unset.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
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
