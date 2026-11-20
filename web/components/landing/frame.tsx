import { Barlow_Condensed, IBM_Plex_Mono } from "next/font/google";
import type { ReactNode } from "react";

// Landing and docs type: a condensed grotesque for headlines, Plex Mono for annotations.
const display = Barlow_Condensed({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-display" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

/** Applies the matte landing theme (see `.landing` in globals.css) and its fonts. */
export function LandingFrame({ children }: { children: ReactNode }) {
  return <div className={`landing min-h-dvh overflow-x-clip ${display.variable} ${plexMono.variable}`}>{children}</div>;
}
