import type { NextConfig } from "next";

const API_URL = process.env.OPSCEND_API_URL ?? "http://127.0.0.1:8000";

// The public site has no API behind it: it serves the landing page and the docs only.
// On by default when building on Vercel; force it either way with OPSCEND_LANDING_ONLY=1 or 0.
const LANDING_ONLY = (process.env.OPSCEND_LANDING_ONLY ?? (process.env.VERCEL ? "1" : "0")) === "1";

const nextConfig: NextConfig = {
  output: "standalone",
  env: {
    NEXT_PUBLIC_OPSCEND_LANDING_ONLY: LANDING_ONLY ? "1" : "0",
    // Only changes wording on the landing page ("Try the live demo"); the API decides the rest.
    NEXT_PUBLIC_OPSCEND_PUBLIC_DEMO: process.env.OPSCEND_PUBLIC_DEMO === "1" ? "1" : "0",
  },
  // The console talks to the FastAPI service through same-origin /api/*,
  // so the session cookie never needs CORS.
  async rewrites() {
    return LANDING_ONLY ? [] : [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  // Without an API the console can only show an error, so send visitors to the setup guide.
  async redirects() {
    if (!LANDING_ONLY) return [];
    return ["/console", "/console/:path*", "/login"].map((source) => ({ source, destination: "/docs", permanent: false }));
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
