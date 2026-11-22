import { Server } from "lucide-react";
import { cn } from "@/lib/format";
import type { Provider } from "@/lib/types";
import { PROVIDER_LOGOS } from "./provider-logos";

export const PROVIDER_META: Record<string, { name: string; color: string }> = {
  vercel: { name: "Vercel", color: "var(--vercel)" },
  railway: { name: "Railway", color: "var(--railway)" },
  github: { name: "GitHub", color: "var(--github)" },
  render: { name: "Render", color: "#7de2d1" },
  fly: { name: "Fly.io", color: "#a78bfa" },
  netlify: { name: "Netlify", color: "#5eead4" },
  cloudflare: { name: "Cloudflare", color: "#f6a04d" },
  aws: { name: "AWS", color: "#f5b544" },
};

export const providerName = (p: Provider) => PROVIDER_META[p]?.name ?? p;
export const providerColor = (p: Provider) => PROVIDER_META[p]?.color ?? "var(--muted)";

/** The provider's real mark in one colour. It takes the surrounding text colour. */
export function ProviderIcon({ provider, size = 14, className }: { provider: Provider; size?: number; className?: string }) {
  const path = PROVIDER_LOGOS[provider];
  if (!path) return <Server size={size} className={className} aria-label={providerName(provider)} />;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" role="img" aria-label={providerName(provider)} className={cn("shrink-0", className)}>
      <path d={path} />
    </svg>
  );
}

/** Icon in a bordered tile; used in lists and cards. */
export function ProviderTile({ provider, size = 28, className }: { provider: Provider; size?: number; className?: string }) {
  return (
    <span
      className={cn("inline-grid shrink-0 place-items-center rounded-md border border-line bg-raised", className)}
      style={{ width: size, height: size }}
    >
      <ProviderIcon provider={provider} size={Math.round(size * 0.5)} />
    </span>
  );
}

export function Logo({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" className={className} aria-hidden>
      <rect width="32" height="32" rx="7" fill="var(--fg)" />
      <path d="M7 21.5 12.5 15l4.5 3.5L24 10" stroke="var(--bg)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="24" cy="10" r="3.4" fill="var(--signal)" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-medium tracking-tight text-fg", className)}>
      <Logo />
      <span className="text-[15px]">opscend</span>
    </span>
  );
}
