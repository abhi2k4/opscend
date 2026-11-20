import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { LandingFrame } from "@/components/landing/frame";
import { Nav } from "@/components/landing/nav";
import { Sherlog } from "@/components/ui/sherlog";

export default function NotFound() {
  return (
    <LandingFrame>
      <Nav />
      <main className="mx-auto grid min-h-[calc(100dvh-3rem)] max-w-[1360px] items-center gap-10 px-5 py-16 sm:px-8 md:grid-cols-[1fr_auto]">
        <div>
          <div className="label">
            <span className="text-[var(--signal)]">404</span>
            <span className="mx-2 text-faint">/</span>
            case closed
          </div>
          <h1 className="display mt-6 text-[clamp(56px,11vw,160px)]">
            No trace
            <br />
            of that page<span className="text-[var(--signal)]">.</span>
          </h1>
          <p className="mt-6 max-w-md text-[16px] leading-relaxed text-muted">Sherlog looked. There is no evidence it was ever here.</p>
          <Link href="/" className="group mt-8 inline-flex h-12 items-center gap-3 bg-fg px-6 text-[15px] font-medium text-bg transition-opacity hover:opacity-85">
            Back to the start <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
          </Link>
        </div>
        <Sherlog size={260} className="justify-self-center" />
      </main>
    </LandingFrame>
  );
}
