"use client";

import { ArrowRight } from "lucide-react";
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { useRef } from "react";
import Link from "next/link";
import { CopyButton } from "@/components/ui/primitives";
import { PRIMARY_CTA } from "@/lib/site";
import { HeroRail } from "./hero-rail";
import { Lines, Rise } from "./reveal";

const FACTS: [string, string][] = [
  ["Watches", "Vercel · Railway · GitHub"],
  ["Writes", "Nothing. Read-only"],
  ["Runs on", "Your machine"],
];

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

  return (
    <section
      ref={ref}
      className="relative"
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
      <div className="mx-auto max-w-[1360px] px-5 pb-20 pt-8 sm:px-8 lg:pb-28 lg:pt-10">
        <div className="relative">
          <h1 className="display text-[clamp(58px,12.2vw,180px)]">
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

        </div>

        <Rise delay={0.35} className="mt-8 lg:mt-10">
          <HeroRail />
        </Rise>

        <div className="mt-10 grid grid-cols-1 gap-x-10 gap-y-10 lg:grid-cols-12">
          <Rise delay={0.5} className="lg:col-span-5">
            <p className="max-w-lg text-[17px] leading-relaxed text-fg/90 sm:text-[19px]">
              One timeline for every deploy. When one fails, it reads the logs and the diff and names the commit.
            </p>
            <div className="mt-8 flex flex-wrap items-stretch gap-3">
              <Link href={PRIMARY_CTA.href} className="group flex h-12 items-center gap-3 bg-fg px-6 text-[15px] font-medium text-bg transition-opacity hover:opacity-85">
                {PRIMARY_CTA.label}
                <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
              </Link>
              <div className="mono flex h-12 items-center gap-3 border border-line pl-4 pr-2 text-[13px]">
                <span className="text-faint">$</span>
                docker compose up
                <CopyButton value="docker compose up" className="size-8" />
              </div>
            </div>
          </Rise>

          <Rise delay={0.62} className="lg:col-span-6 lg:col-start-7">
            <dl className="mono text-[12.5px]">
              {FACTS.map(([k, v]) => (
                <div key={k} className="grid grid-cols-[110px_1fr] gap-4 border-b border-line py-3 first:border-t">
                  <dt className="uppercase tracking-[0.12em] text-muted">{k}</dt>
                  <dd className="text-fg/90">{v}</dd>
                </div>
              ))}
            </dl>
          </Rise>
        </div>
      </div>

    </section>
  );
}
