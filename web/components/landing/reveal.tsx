"use client";

import { motion, useInView, useReducedMotion } from "motion/react";
import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/format";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** Plain rise on scroll. No blur, no scale. */
export function Rise({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 14 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={reduce ? { duration: 0 } : { duration: 0.5, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Headline set line by line; each line slides up from behind its own baseline. */
export function Lines({ lines, className, delay = 0, immediate }: { lines: ReactNode[]; className?: string; delay?: number; immediate?: boolean }) {
  const reduce = useReducedMotion();
  // Watch the wrapper, not the lines: a line starts fully clipped, so it could never see itself enter.
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const shown = immediate || inView || !!reduce;
  return (
    <span ref={ref} className={cn("block", className)}>
      {lines.map((line, i) => (
        <span key={i} className="block overflow-y-clip py-[0.05em]">
          <motion.span
            className="block"
            initial={{ y: "108%" }}
            animate={{ y: shown ? 0 : "108%" }}
            transition={reduce ? { duration: 0 } : { duration: 0.75, delay: delay + i * 0.09, ease: EASE }}
          >
            {line}
          </motion.span>
        </span>
      ))}
    </span>
  );
}

/** Hairline that draws itself from the left. */
export function Rule({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      aria-hidden
      className={cn("h-px origin-left bg-line", className)}
      initial={{ scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={{ once: true }}
      transition={reduce ? { duration: 0 } : { duration: 0.9, ease: EASE }}
    />
  );
}

/**
 * A page section: a short label, a headline, one sentence, then the content.
 * One column with generous space above and below, so each section reads on its own.
 */
export function Section({ id, label, title, lead, children }: { id?: string; label: string; title: ReactNode[]; lead?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-14">
      <div className="mx-auto max-w-[1120px] px-6 py-24 sm:px-8 lg:py-36">
        <Rise>
          <div className="label">{label}</div>
        </Rise>
        <h2 className="display mt-5 text-[clamp(40px,5.6vw,76px)]">
          <Lines lines={title} />
        </h2>
        {lead && (
          <Rise delay={0.15}>
            <p className="mt-6 max-w-xl text-[18px] leading-[1.6] text-fg/75">{lead}</p>
          </Rise>
        )}
        <div className="mt-14 lg:mt-20">{children}</div>
      </div>
    </section>
  );
}
