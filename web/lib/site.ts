/** Site-wide constants. */
export const REPO_URL = "https://github.com/abhi2k4/opscend";
export const API_DOCS_URL = "/api/docs";
export const DOCS_URL = "/docs";
export const VERSION = "0.1.0";

/**
 * True when this build serves only the landing page and docs, with no API behind it
 * (the public site). Set by next.config.ts: on by default on Vercel, off elsewhere.
 */
export const LANDING_ONLY = process.env.NEXT_PUBLIC_OPSCEND_LANDING_ONLY === "1";

/** True when this build fronts the public demo (OPSCEND_PUBLIC_DEMO=1 at build time). */
export const PUBLIC_DEMO = process.env.NEXT_PUBLIC_OPSCEND_PUBLIC_DEMO === "1";

/** The main call to action: the console where there is one, the setup guide where there is not. */
export const PRIMARY_CTA = LANDING_ONLY
  ? { href: DOCS_URL, label: "Read the docs", short: "Docs" }
  : PUBLIC_DEMO
    ? { href: "/console", label: "Try the live demo", short: "Live demo" }
    : { href: "/console", label: "Open the console", short: "Console" };
