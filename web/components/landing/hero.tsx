"use client";

import { ArrowRight, Terminal } from "lucide-react";
import { motion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { ButtonLink, CopyButton } from "@/components/ui/primitives";
import { ProviderIcon } from "@/components/ui/provider";
import { HeroDemo } from "./hero-demo";
import { Words } from "./reveal";

const EASE = [0.21, 0.6, 0.25, 1] as const;

export function Hero() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const gridY = useTransform(scrollYProgress, [0, 1], [0, 140]);
  const demoScale = useTransform(scrollYProgress, [0, 0.6], [1, 0.96]);
  const demoRotate = useTransform(scrollYProgress, [0, 0.35], [7, 0]);

  return (
    <section ref={ref} className="relative overflow-hidden px-4 pb-24 pt-36 sm:pt-44">
      {/* backdrop: grid, beams, glow */}
      <motion.div aria-hidden style={{ y: gridY }} className="bg-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(70%_55%_at_50%_30%,black,transparent)]" />
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        {[12, 31, 54, 73, 90].map((left, i) => (
          <span
            key={left}
            className="absolute top-0 h-40 w-px animate-beam bg-gradient-to-b from-transparent via-accent/70 to-transparent"
            style={{ left: `${left}%`, animationDelay: `${i * 1.7}s`, animationDuration: `${6 + (i % 3) * 2}s` }}
          />
        ))}
      </div>
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-[-18rem] h-[36rem] w-[60rem] -translate-x-1/2 rounded-full opacity-70 blur-3xl"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--accent) 16%, transparent), transparent)" }}
      />

      <div className="relative mx-auto max-w-6xl">
        <div className="mx-auto max-w-3xl text-center">
          <motion.a
            href="#quickstart"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE }}
            className="group mb-7 inline-flex items-center gap-2.5 rounded-full border border-line bg-surface/80 py-1 pl-1 pr-3 text-[12.5px] text-muted backdrop-blur transition-colors hover:border-[#3a3a3f] hover:text-fg"
          >
            <span className="rounded-full bg-accent px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wider text-accent-ink">v0.1</span>
            Open source · self-hosted · bring your own key
            <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
          </motion.a>

          <h1 className="text-balance text-[44px] font-medium leading-[1.02] tracking-[-0.035em] sm:text-[72px]">
            <Words text="Know why the" wordClass="text-gradient" />
            <br />
            <Words text="deploy" wordClass="text-gradient" delay={0.18} />
            <motion.span
              className="relative inline-block text-accent"
              initial={{ opacity: 0, y: "0.4em", filter: "blur(10px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.6, delay: 0.3, ease: EASE }}
            >
              broke.
              <motion.span
                aria-hidden
                className="absolute -bottom-1 left-0 h-[3px] rounded-full bg-accent"
                initial={{ width: 0 }}
                animate={{ width: "100%" }}
                transition={{ duration: 0.7, delay: 0.9, ease: EASE }}
              />
            </motion.span>
          </h1>

          <motion.p
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.45, ease: EASE }}
            className="mx-auto mt-6 max-w-xl text-balance text-[16px] leading-relaxed text-muted sm:text-[17px]"
          >
            One timeline for every <span className="text-fg">Vercel</span>, <span className="text-fg">Railway</span> and{" "}
            <span className="text-fg">GitHub</span> event — and a read-only AI investigator that reads the logs and the diff, then names the commit that broke
            it. With evidence.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.6, ease: EASE }}
            className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
          >
            <ButtonLink href="/console" variant="primary" size="lg" className="group h-11 px-5">
              Open the console
              <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
            </ButtonLink>
            <div className="flex h-11 items-center gap-3 rounded-lg border border-line bg-surface/80 pl-3.5 pr-1.5 font-mono text-[13px] backdrop-blur">
              <Terminal size={14} className="text-faint" />
              <span>
                <span className="text-accent">docker</span> compose up
              </span>
              <CopyButton value="docker compose up" className="size-8" />
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 1, delay: 0.9 }}
            className="mt-8 flex items-center justify-center gap-5 font-mono text-[11px] uppercase tracking-wider text-faint"
          >
            <span>Watches</span>
            {(["vercel", "railway", "github"] as const).map((p) => (
              <span key={p} className="flex items-center gap-1.5 text-muted">
                <ProviderIcon provider={p} size={12} /> {p}
              </span>
            ))}
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 60 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 1, delay: 0.7, ease: EASE }}
          className="mx-auto mt-16 max-w-5xl [perspective:1600px]"
        >
          <motion.div style={{ scale: demoScale, rotateX: demoRotate, transformOrigin: "50% 0%" }}>
            <HeroDemo />
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}
