import { Barlow_Condensed, IBM_Plex_Mono } from "next/font/google";
import { Footer, Integrations, Quickstart } from "@/components/landing/closing";
import { Features } from "@/components/landing/features";
import { Flow } from "@/components/landing/flow";
import { Hero } from "@/components/landing/hero";
import { Investigator } from "@/components/landing/investigator";
import { Nav } from "@/components/landing/nav";

// Landing-only type: a condensed grotesque for headlines, Plex Mono for annotations.
const display = Barlow_Condensed({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-display" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });

export default function Landing() {
  return (
    <div className={`landing overflow-x-clip ${display.variable} ${plexMono.variable}`}>
      <Nav />
      <main>
        <Hero />
        <Flow />
        <Features />
        <Investigator />
        <Integrations />
        <Quickstart />
      </main>
      <Footer />
    </div>
  );
}
