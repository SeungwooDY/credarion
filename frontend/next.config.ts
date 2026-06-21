import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide the dev-only on-screen route/bundler indicator; it sat bottom-left and
  // overlapped the language toggle. Build/runtime errors are still surfaced.
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
