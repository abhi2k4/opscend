import { Footer, Integrations, Quickstart } from "@/components/landing/closing";
import { Features } from "@/components/landing/features";
import { Flow } from "@/components/landing/flow";
import { Hero } from "@/components/landing/hero";
import { Investigator } from "@/components/landing/investigator";
import { Nav } from "@/components/landing/nav";

export default function Landing() {
  return (
    <div className="relative overflow-x-clip">
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
