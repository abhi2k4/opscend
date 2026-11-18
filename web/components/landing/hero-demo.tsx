"use client";

import { AnimatePresence, motion, useInView, useReducedMotion } from "motion/react";
import { FileDiff, GitCommitHorizontal, MousePointer2, Rocket, ScrollText, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ConfidenceMeter, Dot, Tag } from "@/components/ui/primitives";
import { ProviderIcon } from "@/components/ui/provider";
import { cn } from "@/lib/format";

/**
 * Scripted, looping walkthrough of the one demo that defines Opscend:
 * a bad commit fails a Railway deploy, the investigator runs, a report lands.
 * Sample data only — nothing here talks to the API.
 */

// phase → what is on screen
// 0 rows arrive · 1 api deploy building · 2 deploy fails, incident opens
// 3 cursor clicks Investigate · 4 trace runs · 5 report · then loop
const PHASE_MS = [1900, 1900, 1700, 1100, 4300, 6500];

const SPANS = [
  { type: "llm", name: "llm · plan", ms: 612, start: 0 },
  { type: "tool", name: "get_deployment", ms: 41, start: 16 },
  { type: "tool", name: "get_logs  kind=build", ms: 118, start: 19 },
  { type: "tool", name: "get_commit_diff  7c3f2de", ms: 207, start: 24 },
  { type: "tool", name: "list_recent_deploys", ms: 52, start: 32 },
  { type: "llm", name: "llm · reason over evidence", ms: 1338, start: 36 },
  { type: "report", name: "submit_report", ms: 18, start: 96 },
] as const;

const SPAN_COLOR = { llm: "var(--info)", tool: "var(--accent)", report: "var(--ok)" };

export function HeroDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-10% 0px" });
  const reduce = useReducedMotion();
  const [phase, setPhase] = useState(0);

  useEffect(() => {
    if (reduce) {
      setPhase(5);
      return;
    }
    if (!inView) return;
    const t = setTimeout(() => setPhase((p) => (p + 1) % PHASE_MS.length), PHASE_MS[phase]);
    return () => clearTimeout(t);
  }, [phase, inView, reduce]);

  const failed = phase >= 2;
  const apiStatus = phase === 0 ? null : phase === 1 ? "building" : "failed";

  return (
    <div ref={ref} className="relative">
      {/* glow under the window */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-x-10 -top-16 h-72 opacity-60 blur-3xl transition-[background] duration-1000"
        style={{
          background: `radial-gradient(50% 60% at 50% 40%, color-mix(in oklab, ${failed && phase < 5 ? "var(--err)" : "var(--accent)"} 22%, transparent), transparent)`,
        }}
      />
      <div className="relative overflow-hidden rounded-2xl border border-line bg-surface/90 shadow-[0_40px_120px_-20px_rgb(0_0_0/0.9)] backdrop-blur">
        {/* window chrome */}
        <div className="flex h-10 items-center gap-3 border-b border-line px-4">
          <div className="flex gap-1.5">
            {[0, 1, 2].map((i) => (
              <span key={i} className="size-2.5 rounded-full bg-line" />
            ))}
          </div>
          <div className="label-mono flex items-center gap-2 normal-case tracking-normal">
            <span className="text-faint">opscend</span>
            <span className="text-faint">/</span>
            <span className="text-fg">{phase >= 4 ? "investigations / inv_3f9a" : "timeline"}</span>
          </div>
          <div className="ml-auto flex items-center gap-2 font-mono text-[10.5px] uppercase tracking-wider text-muted">
            <Dot color="var(--ok)" pulse />
            live
          </div>
        </div>

        <div className="grid min-h-[380px] md:grid-cols-[1.05fr_1fr]">
          {/* ── timeline ── */}
          <div className="relative border-b border-line p-4 md:border-b-0 md:border-r">
            <div className="label-mono mb-3 flex items-center justify-between">
              <span>Timeline · 3 sources</span>
              <AnimatePresence>
                {failed && (
                  <motion.span initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0 }}>
                    <Tag color="var(--err)">
                      <TriangleAlert size={10} /> 1 incident
                    </Tag>
                  </motion.span>
                )}
              </AnimatePresence>
            </div>

            <div className="relative space-y-2">
              <span aria-hidden className="absolute bottom-3 left-[13px] top-3 w-px bg-line" />
              <AnimatePresence initial={false}>
                {apiStatus && (
                  <Row key="api" provider="railway" accent={apiStatus === "failed" ? "var(--err)" : "var(--warn)"} shake={phase === 2}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">storefront-api</span>
                      <Tag color={apiStatus === "failed" ? "var(--err)" : "var(--warn)"}>
                        <Dot color={apiStatus === "failed" ? "var(--err)" : "var(--warn)"} pulse={apiStatus === "building"} className="scale-75" />
                        {apiStatus}
                      </Tag>
                    </div>
                    <div className="mt-1 flex items-center gap-2 font-mono text-[11px] text-muted">
                      <Rocket size={11} /> deploy · 7c3f2de · main
                      <span className="ml-auto text-faint">{apiStatus === "failed" ? "48s" : "…"}</span>
                    </div>
                    <AnimatePresence>
                      {failed && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-line pt-2.5">
                            <span className="truncate font-mono text-[11px] text-err">KeyError: &apos;STRIPE_SECRET_KEY&apos;</span>
                            <span
                              className={cn(
                                "relative inline-flex h-6 shrink-0 items-center gap-1.5 rounded-md px-2 text-[11.5px] font-medium transition-all duration-200",
                                phase >= 3 ? "bg-accent text-accent-ink" : "border border-line bg-raised text-fg",
                                phase === 3 && "scale-95",
                              )}
                            >
                              <Sparkles size={11} /> Investigate
                              {phase === 3 && <span className="absolute inset-0 animate-pulse-ring rounded-md bg-accent/50" />}
                            </span>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </Row>
                )}
                <Row key="commit" provider="github" delay={0.5}>
                  <div className="truncate">refactor: read stripe secret from env</div>
                  <div className="mt-1 flex items-center gap-2 font-mono text-[11px] text-muted">
                    <GitCommitHorizontal size={11} /> 7c3f2de · priya
                    <span className="ml-auto text-faint">acme/storefront</span>
                  </div>
                </Row>
                <Row key="web" provider="vercel" delay={0.25}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">storefront-web</span>
                    <Tag color="var(--ok)">
                      <Dot color="var(--ok)" className="scale-75" />
                      ready
                    </Tag>
                  </div>
                  <div className="mt-1 flex items-center gap-2 font-mono text-[11px] text-muted">
                    <Rocket size={11} /> deploy · a1b9e04 · main
                    <span className="ml-auto text-faint">31s</span>
                  </div>
                </Row>
              </AnimatePresence>
            </div>

            {/* fake cursor */}
            <AnimatePresence>
              {(phase === 2 || phase === 3) && (
                <motion.div
                  className="pointer-events-none absolute z-10 text-fg drop-shadow-[0_2px_6px_rgb(0_0_0/0.8)]"
                  initial={{ opacity: 0, right: "55%", top: "88%" }}
                  animate={{ opacity: 1, right: "7%", top: "112px" }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 1.1, delay: 0.5, ease: [0.3, 0.7, 0.2, 1] }}
                >
                  <MousePointer2 size={18} fill="currentColor" stroke="#000" strokeWidth={1} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* ── right pane ── */}
          <div className="relative p-4">
            <AnimatePresence mode="wait">
              {phase < 4 && <Idle key="idle" failed={failed} />}
              {phase === 4 && <Trace key="trace" />}
              {phase === 5 && <Report key="report" />}
            </AnimatePresence>
          </div>
        </div>

        {/* progress rail */}
        <div className="flex gap-1 border-t border-line px-4 py-2.5">
          {["Deploys land", "Build runs", "Deploy fails", "Investigate", "Trace", "Report"].map((l, i) => (
            <div key={l} className="flex-1">
              <div className="h-0.5 overflow-hidden rounded-full bg-line">
                {i < phase && <div className="h-full w-full bg-muted" />}
                {i === phase && (
                  <motion.div
                    key={phase}
                    className="h-full bg-accent"
                    initial={{ width: "0%" }}
                    animate={{ width: "100%" }}
                    transition={{ duration: PHASE_MS[i] / 1000, ease: "linear" }}
                  />
                )}
              </div>
              <div className={cn("mt-1.5 hidden font-mono text-[10px] uppercase tracking-wider sm:block", i === phase ? "text-fg" : "text-faint")}>{l}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function Row({
  provider,
  children,
  accent,
  delay = 0,
  shake,
}: {
  provider: string;
  children: React.ReactNode;
  accent?: string;
  delay?: number;
  shake?: boolean;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -14, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)", x: shake ? [0, -5, 5, -3, 3, 0] : 0 }}
      exit={{ opacity: 0, transition: { duration: 0.2 } }}
      transition={{ duration: 0.5, delay, layout: { duration: 0.4 } }}
      className="relative flex gap-3"
    >
      <span className="relative z-[1] mt-1.5 grid size-[27px] shrink-0 place-items-center rounded-md border border-line bg-raised">
        <ProviderIcon provider={provider} size={12} />
      </span>
      <div
        className="min-w-0 flex-1 rounded-lg border bg-bg/60 px-3 py-2.5 text-[12.5px] transition-colors duration-500"
        style={{ borderColor: accent ? `color-mix(in oklab, ${accent} 45%, var(--line))` : "var(--line)" }}
      >
        {children}
      </div>
    </motion.div>
  );
}

const pane = {
  initial: { opacity: 0, y: 10, filter: "blur(6px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  exit: { opacity: 0, y: -8, filter: "blur(6px)" },
  transition: { duration: 0.35 },
};

function Idle({ failed }: { failed: boolean }) {
  return (
    <motion.div {...pane} className="flex h-full flex-col">
      <div className="label-mono mb-3">Build log · storefront-api</div>
      <div className="code flex-1 space-y-1 overflow-hidden text-[11px]">
        {[
          ["info", "Cloning acme/storefront @ 7c3f2de"],
          ["info", "pip install -r requirements.txt"],
          ["info", "Running alembic upgrade head"],
          ["info", "Starting uvicorn app.main:app"],
        ].map(([lvl, msg], i) => (
          <motion.div key={msg} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.3 + i * 0.35 }} className="flex gap-2">
            <span className="w-9 shrink-0 uppercase text-info">{lvl}</span>
            <span className="truncate text-muted">{msg}</span>
          </motion.div>
        ))}
        {failed && (
          <>
            {["  File \"app/config.py\", line 14, in <module>", "KeyError: 'STRIPE_SECRET_KEY'", "Process exited with code 1"].map((msg, i) => (
              <motion.div key={msg} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.12 }} className="flex gap-2 rounded-sm bg-err/10">
                <span className="w-9 shrink-0 uppercase text-err">error</span>
                <span className="truncate text-fg">{msg}</span>
              </motion.div>
            ))}
          </>
        )}
        <span className="inline-block h-3.5 w-1.5 animate-caret bg-muted" />
      </div>
    </motion.div>
  );
}

function Trace() {
  return (
    <motion.div {...pane}>
      <div className="label-mono mb-3 flex items-center justify-between">
        <span>Agent run · investigator</span>
        <span className="flex items-center gap-1.5 text-accent">
          <span className="size-1.5 animate-pulse rounded-full bg-accent" /> running
        </span>
      </div>
      <div className="space-y-1.5">
        {SPANS.map((s, i) => (
          <motion.div
            key={s.name}
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.5, duration: 0.3 }}
            className="grid grid-cols-[minmax(0,1.3fr)_1fr_46px] items-center gap-2 font-mono text-[11px]"
          >
            <span className="flex items-center gap-2 truncate" style={{ paddingLeft: s.type === "tool" ? 12 : 0 }}>
              <span className="size-1.5 shrink-0 rounded-[2px]" style={{ background: SPAN_COLOR[s.type] }} />
              <span className="truncate text-fg/90">{s.name}</span>
            </span>
            <span className="relative h-1.5 rounded-full bg-line/60">
              <motion.span
                className="absolute inset-y-0 rounded-full"
                style={{ left: `${s.start}%`, background: SPAN_COLOR[s.type] }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(4, Math.min(100 - s.start, s.ms / 22))}%` }}
                transition={{ delay: i * 0.5 + 0.1, duration: 0.45, ease: "easeOut" }}
              />
            </span>
            <span className="text-right text-muted">{s.ms}ms</span>
          </motion.div>
        ))}
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2">
        {[
          { icon: ScrollText, label: "61 log lines" },
          { icon: FileDiff, label: "2 files changed" },
          { icon: Rocket, label: "4 recent deploys" },
        ].map((c, i) => (
          <motion.div
            key={c.label}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.2 + i * 0.5 }}
            className="flex items-center gap-1.5 rounded-md border border-line bg-bg/60 px-2 py-1.5 font-mono text-[10.5px] text-muted"
          >
            <c.icon size={11} className="shrink-0 text-faint" /> <span className="truncate">{c.label}</span>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

function Report() {
  const item = (i: number) => ({
    initial: { opacity: 0, y: 8 },
    animate: { opacity: 1, y: 0 },
    transition: { delay: 0.15 + i * 0.22, duration: 0.4 },
  });
  return (
    <motion.div {...pane}>
      <div className="label-mono mb-3 flex items-center justify-between">
        <span>Report</span>
        <span className="text-faint">7 steps · 2.4s · 3.1k tokens</span>
      </div>
      <motion.div {...item(0)} className="mb-3 flex items-center justify-between">
        <span className="label-mono">Likely cause</span>
        <ConfidenceMeter confidence="high" />
      </motion.div>
      <motion.p {...item(1)} className="text-[13.5px] leading-relaxed text-fg">
        Commit <code className="rounded-sm bg-raised px-1 font-mono text-[12px] text-accent">7c3f2de</code> renamed{" "}
        <code className="font-mono text-[12px]">STRIPE_SECRET</code> to <code className="font-mono text-[12px]">STRIPE_SECRET_KEY</code>, but the Railway
        service only defines the old name. The API crashes on boot.
      </motion.p>
      <motion.div {...item(2)} className="label-mono mb-2 mt-4">
        Evidence · 3 cited
      </motion.div>
      <div className="space-y-1.5">
        {[
          { tag: "log", color: "var(--err)", ref: "log_41", quote: "KeyError: 'STRIPE_SECRET_KEY'" },
          { tag: "commit", color: "var(--github)", ref: "7c3f2de", quote: "app/config.py  +1 −1" },
          { tag: "deploy", color: "var(--ok)", ref: "dpl_a1b9", quote: "Vercel deploy healthy → not the frontend" },
        ].map((e, i) => (
          <motion.div key={e.ref} {...item(3 + i)} className="flex items-center gap-2 rounded-md border border-line bg-bg/60 px-2 py-1.5 font-mono text-[11px]">
            <Tag color={e.color}>{e.tag}</Tag>
            <span className="text-muted">{e.ref}</span>
            <span className="truncate text-fg/90">{e.quote}</span>
          </motion.div>
        ))}
      </div>
      <motion.div {...item(6)} className="mt-3 rounded-md border border-accent/25 bg-accent/[0.06] px-3 py-2 text-[12px] leading-relaxed text-fg/90">
        <span className="label-mono mr-2 text-accent">Suggested fix</span>
        Add <code className="font-mono">STRIPE_SECRET_KEY</code> to the Railway service variables, then redeploy.
      </motion.div>
    </motion.div>
  );
}
