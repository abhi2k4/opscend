"use client";

import { ArrowRight } from "lucide-react";
import { motion, useMotionTemplate, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { CopyButton } from "@/components/ui/primitives";
import { PRIMARY_CTA } from "@/lib/site";
import { HeroDemo } from "./hero-demo";
import { HeroRail } from "./hero-rail";
import { Lines, Rise } from "./reveal";

const FACTS: [string, string][] = [
  ["Watches", "Vercel · Railway · GitHub"],
  ["Writes", "Nothing. Read-only"],
  ["Runs on", "Your machine"],
];

const TAPE = [
  "railway · storefront-api · deploy 7c3f2de · FAILED 48s",
  "incident opened · storefront-api",
  "github · push · acme/storefront · 7c3f2de",
  "vercel · storefront-web · deploy a1b9e04 · ready 31s",
  "investigator · 7 steps · 2.4s · cause: 7c3f2de",
  "webhook evt_8842 · duplicate · dropped",
  "poller · reconcile · 0 missed",
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

  // Every time the failed deploy crosses "now" on the rail, the stamp lands again.
  const [thumps, setThumps] = useState(0);
  const onFailure = useCallback(() => setThumps((n) => n + 1), []);

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
      <div className="mx-auto max-w-[1360px] px-5 pb-14 pt-8 sm:px-8 lg:pt-10">
        <div className="label flex flex-wrap items-center justify-between gap-3">
          <span>
            <span className="text-fg">Opscend</span>
            <span className="mx-2 text-faint">/</span>
            deploy investigator
          </span>
          <span>v0.1 · open source · self-hosted</span>
        </div>

        <div className="relative mt-6 lg:mt-8">
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

          {/* rubber stamp, thumped on after the headline lands */}
          <motion.div
            aria-hidden
            key={thumps}
            initial={{ opacity: 0, scale: 1.45, rotate: -3 }}
            animate={{ opacity: 1, scale: 1, rotate: -7 }}
            transition={reduce ? { duration: 0 } : { delay: thumps === 0 ? 1.05 : 0, type: "spring", stiffness: 520, damping: 24, mass: 0.7 }}
            className="mono absolute right-0 top-[8%] hidden border-2 border-[var(--signal)] px-3 py-2 text-[12px] uppercase leading-tight tracking-[0.14em] text-[var(--signal)] md:block lg:right-[4%] lg:px-4 lg:py-2.5 lg:text-[13px]"
          >
            <div className="text-[1.5em] font-medium tracking-[0.2em]">Failed</div>
            <div>railway · 7c3f2de</div>
            <div className="opacity-70">exit code 1 · 48s</div>
          </motion.div>
        </div>

        <Rise delay={0.35} className="mt-8 lg:mt-10">
          <div className="label mb-2 flex items-center justify-between">
            <span>Fig. 0 — one timeline, three sources</span>
            <span className="hidden sm:block">sample data</span>
          </div>
          <HeroRail onFailure={onFailure} />
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

      {/* event tape */}
      <div className="overflow-hidden border-y border-line bg-surface" aria-hidden>
        <div className="mono flex w-max animate-marquee whitespace-nowrap py-2.5 text-[11.5px] uppercase tracking-[0.1em] text-muted">
          {[...TAPE, ...TAPE].map((t, i) => (
            <span key={i} className="flex items-center">
              <span className={t.includes("FAILED") || t.includes("incident") ? "text-[var(--signal)]" : ""}>{t}</span>
              <span className="mx-6 text-faint">+</span>
            </span>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-[1360px] px-5 py-14 sm:px-8 lg:py-20">
        <div className="label mb-4 flex items-center justify-between">
          <span>Fig. 1 — the whole product, in one loop</span>
          <span className="hidden sm:block">loops every 17s</span>
        </div>
        <Rise>
          <HeroDemo />
        </Rise>
      </div>
    </section>
  );
}
