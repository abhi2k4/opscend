"use client";

import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { cn } from "@/lib/format";

const EASE = [0.21, 0.6, 0.25, 1] as const;

/** Fade-and-rise on scroll into view. */
export function Reveal({ children, delay = 0, className, y = 18 }: { children: ReactNode; delay?: number; className?: string; y?: number }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y, filter: "blur(6px)" }}
      whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.7, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Headline that resolves word by word. */
export function Words({ text, className, wordClass, delay = 0, dim }: { text: string; className?: string; wordClass?: string; delay?: number; dim?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <span className={className}>
      {text.split(" ").map((w, i) => (
        <motion.span
          key={i}
          className={cn("inline-block whitespace-pre", dim && "text-muted", wordClass)}
          initial={reduce ? false : { opacity: 0, y: "0.4em", filter: "blur(10px)" }}
          whileInView={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          viewport={{ once: true }}
          transition={{ duration: 0.6, delay: delay + i * 0.055, ease: EASE }}
        >
          {w}{" "}
        </motion.span>
      ))}
    </span>
  );
}

export function SectionHeading({ eyebrow, lead, rest, className }: { eyebrow: string; lead: string; rest: string; className?: string }) {
  return (
    <div className={cn("mx-auto max-w-3xl text-center", className)}>
      <Reveal>
        <div className="label-mono mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1">
          <span className="size-1.5 rounded-full bg-accent" />
          {eyebrow}
        </div>
      </Reveal>
      <h2 className="text-balance text-[30px] font-medium leading-[1.12] tracking-[-0.02em] sm:text-[42px]">
        <Words text={lead} />
        <Words text={rest} dim delay={lead.split(" ").length * 0.055} />
      </h2>
    </div>
  );
}
