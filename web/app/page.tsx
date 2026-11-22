import { Footer, Integrations, Quickstart } from "@/components/landing/closing";
import { LandingFrame } from "@/components/landing/frame";
import { HashScroll } from "@/components/landing/hash-scroll";
import { Hero } from "@/components/landing/hero";
import { Investigator } from "@/components/landing/investigator";
import { Nav } from "@/components/landing/nav";
import { Story } from "@/components/landing/story";

export default function Landing() {
  return (
    <LandingFrame>
      <HashScroll />
      <Nav />
      <main>
        <Hero />
        <Story />
        <Investigator />
        <Integrations />
        <Quickstart />
      </main>
      <Footer />
    </LandingFrame>
  );
}
