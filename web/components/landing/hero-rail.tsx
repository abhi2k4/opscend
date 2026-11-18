"use client";

import { AnimatePresence, motion, useAnimationFrame, useInView, useMotionValue, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/format";

/**
 * The product in one moving line: deploys and commits travel along a rail,
 * and when the failed one crosses "now" the readout (and the hero stamp) react.
 * Sample data. One rAF loop drives the whole strip.
 */

type Kind = "ready" | "commit" | "failed";
interface Mark {
  at: number; // px along one period
  kind: Kind;
  label: string;
}

const PERIOD = 1560;
const SPEED = 46; // px per second
const MARKS: Mark[] = [
  { at: 60, kind: "commit", label: "a1b9e04" },
  { at: 170, kind: "ready", label: "storefront-web · 31s" },
  { at: 400, kind: "commit", label: "e77c0d2" },
  { at: 500, kind: "ready", label: "worker · 44s" },
  { at: 730, kind: "ready", label: "storefront-web · 29s" },
  { at: 960, kind: "commit", label: "7c3f2de" },
  { at: 1070, kind: "failed", label: "storefront-api · exit 1" },
  { at: 1330, kind: "ready", label: "storefront-api · 52s" },
];
const FAILED_AT = MARKS.find((m) => m.kind === "failed")!.at;
/** How long after crossing "now" the failure stays on the readout, in px of travel. */
const HOLD = 150;

export function HeroRail({ onFailure }: { onFailure?: () => void }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref);
  const x = useMotionValue(0);
  const [width, setWidth] = useState(1360);
  const [hit, setHit] = useState(false);
  const hitRef = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.offsetWidth));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const now = Math.round(width * 0.7);

  useAnimationFrame((_, delta) => {
    if (reduce || !inView) return;
    // Clamp the step so a background tab does not jump the strip on return.
    const next = (x.get() - (SPEED * Math.min(delta, 64)) / 1000) % PERIOD;
    x.set(next);
    // Distance the failed mark has travelled past the playhead, in any copy.
    const past = (((now - (FAILED_AT + next)) % PERIOD) + PERIOD) % PERIOD;
    const isHit = past < HOLD;
    if (isHit !== hitRef.current) {
      hitRef.current = isHit;
      setHit(isHit);
      if (isHit) onFailure?.();
    }
  });

  const copies = Math.ceil(width / PERIOD) + 2;

  return (
    <div ref={ref} className="relative h-[108px] select-none overflow-hidden border-y border-line" aria-hidden>
      {/* moving strip */}
      <motion.div className="absolute inset-y-0 left-0 will-change-transform" style={{ x }}>
        {Array.from({ length: copies }, (_, c) => (
          <div key={c} className="absolute inset-y-0" style={{ left: c * PERIOD, width: PERIOD }}>
            {/* ruler */}
            {Array.from({ length: PERIOD / 26 }, (_, i) => (
              <span key={i} className={cn("absolute bottom-0 w-px bg-line", i % 5 === 0 ? "h-3" : "h-1.5")} style={{ left: i * 26 }} />
            ))}
            {MARKS.map((m) => (
              <div key={m.at} className="absolute bottom-0 top-0" style={{ left: m.at }}>
                {m.kind === "failed" ? (
                  <>
                    <span className="absolute bottom-0 left-0 h-[62px] w-px bg-[var(--signal)]" />
                    <span className="absolute bottom-[56px] left-[-6px] size-[13px] bg-[var(--signal)]" />
                    <span className="mono absolute bottom-[55px] left-[16px] whitespace-nowrap text-[10.5px] uppercase tracking-[0.12em] text-[var(--signal)]">{m.label}</span>
                  </>
                ) : m.kind === "ready" ? (
                  <>
                    <span className="absolute bottom-0 left-0 h-[34px] w-px bg-line" />
                    <span className="absolute bottom-[30px] left-[-4px] size-[9px] bg-fg" />
                    <span className="mono absolute bottom-[46px] left-[-4px] whitespace-nowrap text-[10.5px] uppercase tracking-[0.12em] text-muted">{m.label}</span>
                  </>
                ) : (
                  <>
                    <span className="absolute bottom-0 left-0 h-[18px] w-px bg-line" />
                    <span className="absolute bottom-[15px] left-[-4px] size-[8px] rotate-45 border border-muted bg-bg" />
                    <span className="mono absolute bottom-[28px] left-[10px] whitespace-nowrap text-[10px] tracking-[0.08em] text-faint">{m.label}</span>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </motion.div>

      {/* edges fall off into the page instead of being cut */}
      <span className="absolute inset-y-0 left-0 w-10 bg-bg [mask-image:linear-gradient(to_right,black,transparent)]" />
      <span className="absolute inset-y-0 right-0 w-10 bg-bg [mask-image:linear-gradient(to_left,black,transparent)]" />

      {/* playhead */}
      <div className="absolute inset-y-0" style={{ left: now }}>
        <span className={cn("absolute inset-y-0 left-0 w-px transition-colors duration-500", hit ? "bg-[var(--signal)]" : "bg-fg")} />
        <span className={cn("mono absolute left-2 top-2 text-[10px] uppercase tracking-[0.16em] transition-colors duration-500", hit ? "text-[var(--signal)]" : "text-fg")}>now</span>
      </div>

      {/* readout */}
      <div className="mono absolute right-0 top-0 hidden h-7 items-center overflow-hidden border-b border-l border-line bg-bg px-3 text-[10.5px] uppercase tracking-[0.12em] sm:flex">
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={hit ? "failed" : "ok"}
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -14, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.2, 0.7, 0.2, 1] }}
            className={hit ? "text-[var(--signal)]" : "text-muted"}
          >
            {hit ? "failed · 7c3f2de · incident opened" : "all services ready"}
          </motion.span>
        </AnimatePresence>
      </div>
    </div>
  );
}
