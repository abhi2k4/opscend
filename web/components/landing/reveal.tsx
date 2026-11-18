"use client";

import { motion, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
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
 * Page section laid out like a spec sheet: a narrow margin column carrying the
 * section number, and a wide column carrying the content.
 */
export function Section({ id, no, label, title, lead, children }: { id?: string; no: string; label: string; title: ReactNode[]; lead?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-14">
      <Rule />
      <div className="mx-auto grid max-w-[1360px] grid-cols-1 gap-x-10 px-5 sm:px-8 lg:grid-cols-12">
        <div className="pt-6 lg:col-span-2 lg:pt-10">
          <div className="label lg:sticky lg:top-20">
            <span className="text-fg">§{no}</span>
            <span className="mx-2 text-faint">/</span>
            {label}
          </div>
        </div>
        <div className="min-w-0 pb-20 pt-6 lg:col-span-10 lg:pb-28 lg:pt-10">
          <div className="grid grid-cols-1 items-end gap-x-10 gap-y-6 lg:grid-cols-10">
            <h2 className="display text-[clamp(44px,6.4vw,92px)] lg:col-span-7">
              <Lines lines={title} />
            </h2>
            {lead && (
              <Rise delay={0.15} className="lg:col-span-3">
                <p className="max-w-md text-[15px] leading-relaxed text-muted">{lead}</p>
              </Rise>
            )}
          </div>
          <div className="mt-12 lg:mt-16">{children}</div>
        </div>
      </div>
    </section>
  );
}

/**
 * Animates its own height to follow its content, so swapping or growing
 * content eases the layout instead of snapping it.
 */
export function SmoothHeight({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");

  useEffect(() => {
    const el = inner.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setHeight(el.offsetHeight));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <motion.div className={cn("overflow-hidden", className)} initial={false} animate={{ height }} transition={reduce ? { duration: 0 } : { duration: 0.5, ease: EASE }}>
      <div ref={inner}>{children}</div>
    </motion.div>
  );
}
