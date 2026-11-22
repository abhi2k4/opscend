"use client";

import { ArrowRight, ArrowUpRight } from "lucide-react";
import { AnimatePresence, motion, useMotionTemplate, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { ProviderIcon } from "@/components/ui/provider";
import { PRIMARY_CTA, REPO_URL } from "@/lib/site";
import { Sherlog } from "@/components/ui/sherlog";
import { HeroLens } from "./hero-lens";
import { Lines, Rise } from "./reveal";

export function Hero() {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);

  // The outlined ghost of "broke." drifts with the pointer, like a loose printing plate.
  const px = useSpring(useMotionValue(0), { stiffness: 60, damping: 16, mass: 0.6 });
  const py = useSpring(useMotionValue(0), { stiffness: 60, damping: 16, mass: 0.6 });
  const gx = useTransform(px, (v) => 0.03 + v * 0.028);
  const gy = useTransform(py, (v) => 0.028 + v * 0.022);
  const ghost = useMotionTemplate`${gx}em ${gy}em`;

  // Headline lines drift apart slightly as the page scrolls away.
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const drift = useSpring(scrollYProgress, { stiffness: 90, damping: 24 });
  const lineA = useTransform(drift, [0, 1], ["0%", "2%"]);
  const lineB = useTransform(drift, [0, 1], ["0%", "6%"]);
  const lineC = useTransform(drift, [0, 1], ["0%", "11%"]);

  // The glass in the backdrop reports when it has come to rest on the failing line.
  const [found, setFound] = useState(false);
  const onFound = useCallback((value: boolean) => setFound(value), []);

  return (
    <section
      ref={ref}
      className="relative overflow-hidden"
      onPointerMove={(e) => {
        if (reduce || e.pointerType === "touch") return;
        const r = e.currentTarget.getBoundingClientRect();
        px.set(((e.clientX - r.left) / r.width) * 2 - 1);
        py.set(Math.min(1, ((e.clientY - r.top) / Math.min(r.height, 900)) * 2 - 1));
      }}
      onPointerLeave={() => {
        px.set(0);
        py.set(0);
      }}
    >
      <HeroLens onFound={onFound} reduce={!!reduce} />

      <div className="relative mx-auto max-w-[1120px] px-6 pt-14 sm:px-8 lg:pt-16">
        <Rise>
          <div className="label">Open source · self-hosted</div>
        </Rise>
        <h1 className="display mt-6 text-[clamp(54px,9.4vw,124px)]">
          <Lines
            immediate
            lines={[
              <motion.span key="a" className="block" style={{ x: reduce ? 0 : lineA }}>
                Know why
              </motion.span>,
              <motion.span key="b" className="block" style={{ x: reduce ? 0 : lineB }}>
                the deploy
              </motion.span>,
              <motion.span key="c" className="block" style={{ x: reduce ? 0 : lineC }}>
                <span className="misreg">
                  <span>broke.</span>
                  <motion.span aria-hidden className="ghost" style={{ translate: reduce ? "0.03em 0.028em" : ghost }}>
                    broke.
                  </motion.span>
                </span>
              </motion.span>,
            ]}
          />
        </h1>

        <Rise delay={0.35}>
          <p className="mt-8 max-w-xl text-[19px] leading-[1.6] text-fg/80 sm:text-[21px]">
            Connect the platforms you deploy to. When a deploy fails, Opscend reads the logs and the diff and tells you which commit did it.
          </p>
        </Rise>
        <Rise delay={0.45} className="mt-9 flex flex-wrap items-center gap-x-7 gap-y-4">
          <Link href={PRIMARY_CTA.href} className="group flex h-12 items-center gap-3 bg-fg px-6 text-[15px] font-medium text-bg transition-opacity hover:opacity-85">
            {PRIMARY_CTA.label}
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
          </Link>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="group inline-flex items-center gap-2 text-[15px] text-fg/80 transition-colors hover:text-fg">
            <ProviderIcon provider="github" size={16} /> View the source
            <ArrowUpRight size={14} className="text-muted transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
          </a>
        </Rise>

        {/* What the glass is for, and what happens when it finds the line. */}
        <Rise delay={0.6}>
          <div className="mono mt-10 h-10 max-w-md text-[12.5px] leading-5 text-muted" aria-live="polite">
            <AnimatePresence mode="wait" initial={false}>
              <motion.p key={found ? "found" : "look"} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: reduce ? 0 : 0.3 }}>
                {found ? (
                  <>
                    <span className="text-[var(--signal)]">Found it.</span> Opscend does this for every failed deploy.
                  </>
                ) : (
                  <>
                    Somewhere in this noise is the line that broke the deploy. <span className="hidden lg:inline">Move the glass to find it.</span>
                    <span className="lg:hidden">Sherlog&apos;s glass is looking for it.</span>
                  </>
                )}
              </motion.p>
            </AnimatePresence>
          </div>
        </Rise>
        {/* On narrow screens the glass works in its own strip below the copy. */}
        <div className="h-60 lg:h-16" aria-hidden />
        <Sherlog size={128} mood={found ? "alert" : "calm"} className="absolute bottom-0 right-8 hidden lg:block" />
      </div>

    </section>
  );
}
