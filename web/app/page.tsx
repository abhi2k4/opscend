import { Footer, Integrations, Quickstart } from "@/components/landing/closing";
import { Features } from "@/components/landing/features";
import { Flow } from "@/components/landing/flow";
import { LandingFrame } from "@/components/landing/frame";
import { Hero } from "@/components/landing/hero";
import { Investigator } from "@/components/landing/investigator";
import { Nav } from "@/components/landing/nav";

export default function Landing() {
  return (
    <LandingFrame>
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
    </LandingFrame>
  );
}
