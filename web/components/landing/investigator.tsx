"use client";

import { motion } from "motion/react";
import { Ban, Eye, FileSearch, Gauge, KeyRound, Sparkles } from "lucide-react";
import { LevelBadge, Spotlight, Tag } from "@/components/ui/primitives";
import type { LogLevel } from "@/lib/types";
import { Reveal, SectionHeading } from "./reveal";

const LOGS: [LogLevel, string][] = [
  ["info", "Cloning acme/storefront @ 7c3f2de"],
  ["info", "Detected Python 3.13 · installing dependencies"],
  ["debug", "Resolved 84 packages in 1.92s"],
  ["info", "Running alembic upgrade head"],
  ["debug", "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl"],
  ["warn", "Deprecated: pydantic.v1 import in app/schemas/legacy.py"],
  ["info", "Starting uvicorn app.main:app --port $PORT"],
  ["error", "Traceback (most recent call last):"],
  ["error", '  File "app/config.py", line 14, in <module>'],
  ["error", "KeyError: 'STRIPE_SECRET_KEY'"],
  ["warn", "Health check /healthz failed (1/3)"],
  ["warn", "Health check /healthz failed (2/3)"],
  ["error", "Process exited with code 1"],
  ["info", "Deployment marked FAILED after 48.2s"],
  ["debug", "webhook delivered deployment.failed id=evt_8842"],
  ["debug", "webhook delivered deployment.failed id=evt_8842 (duplicate, dropped)"],
];

const SCENARIOS = [
  { name: "Bad env var", breaks: "Renamed secret, service config not updated", layer: "runtime" },
  { name: "Syntax error", breaks: "Unclosed bracket lands on main", layer: "build" },
  { name: "Failing migration", breaks: "Column dropped before the code stops reading it", layer: "release" },
  { name: "Dependency bump", breaks: "Major version changes an import path", layer: "build" },
  { name: "Timeout", breaks: "Blocking call in the health handler", layer: "runtime" },
];

const GUARDRAILS = [
  { icon: Ban, title: "No write path", body: "The toolset has five read tools and nothing else. No rollback, no restart." },
  { icon: FileSearch, title: "Evidence or nothing", body: "Reports cite log, commit and deploy ids. Unverifiable citations are dropped." },
  { icon: Eye, title: "Every step is a span", body: "Each model turn and tool call is stored with its input, output and duration." },
  { icon: Gauge, title: "Bounded runs", body: "At most eight tool calls and a fixed token budget. Then it must answer." },
  { icon: KeyRound, title: "Your key, your box", body: "Self-hosted. Tokens are Fernet-encrypted and never reach the model." },
  { icon: Sparkles, title: "Allowed to say “I don't know”", body: "Inconclusive is a valid report, with a note on what data was missing." },
];

export function Investigator() {
  const doubled = [...LOGS, ...LOGS];
  return (
    <section id="investigator" className="relative px-4 py-28">
      <SectionHeading eyebrow="AI investigator" lead="It reads the logs so you don't." rest="Then it shows its work: every tool call traced, every claim cited." />

      <div className="mx-auto mt-14 grid max-w-6xl gap-4 lg:grid-cols-[1.1fr_1fr]">
        {/* log wall */}
        <Reveal>
          <Spotlight className="panel relative h-[440px] overflow-hidden">
            <div className="flex h-10 items-center justify-between border-b border-line px-4">
              <span className="label-mono">storefront-api · build + runtime</span>
              <span className="flex gap-1.5">
                <Tag color="var(--err)">4 errors</Tag>
                <Tag color="var(--warn)">3 warnings</Tag>
              </span>
            </div>
            <div className="mask-fade-y h-[400px] overflow-hidden">
              <div className="animate-marquee-y space-y-px py-2 hover:[animation-play-state:paused]">
                {doubled.map(([lvl, msg], i) => (
                  <div key={i} className={`flex items-center gap-3 px-4 py-[5px] font-mono text-[11.5px] ${lvl === "error" ? "bg-err/[0.07]" : ""}`}>
                    <span className="w-16 shrink-0 text-faint">14:25:{String(10 + (i % LOGS.length) * 3).padStart(2, "0")}</span>
                    <LevelBadge level={lvl} />
                    <span className={`truncate ${lvl === "error" ? "text-fg" : "text-muted"}`}>{msg}</span>
                  </div>
                ))}
              </div>
            </div>
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: 0.6, duration: 0.6 }}
              className="absolute inset-x-4 bottom-4 flex items-center justify-between gap-3 rounded-xl border border-line bg-raised/95 p-3 pl-4 shadow-[0_20px_60px_rgb(0_0_0/0.8)] backdrop-blur"
            >
              <div>
                <div className="text-[13px] font-medium">Deploy failed · 1 incident opened</div>
                <div className="font-mono text-[11px] text-muted">railway · storefront-api · 7c3f2de</div>
              </div>
              <span className="relative inline-flex h-8 items-center gap-2 rounded-lg bg-accent px-3 text-[13px] font-medium text-accent-ink">
                <span className="absolute inset-0 animate-pulse-ring rounded-lg bg-accent/40" />
                <Sparkles size={13} className="relative" />
                <span className="relative">Investigate</span>
              </span>
            </motion.div>
          </Spotlight>
        </Reveal>

        {/* scenario suite */}
        <Reveal delay={0.1}>
          <Spotlight className="panel flex h-[440px] flex-col overflow-hidden">
            <div className="flex h-10 items-center justify-between border-b border-line px-4">
              <span className="label-mono">Chaos lab · 5 scripted failures</span>
              <span className="label-mono hidden text-faint xl:block">in the repo</span>
            </div>
            <div className="grid grid-cols-[1.1fr_2fr_auto] gap-3 border-b border-line px-4 py-2 font-mono text-[10.5px] uppercase tracking-wider text-faint">
              <span>Scenario</span>
              <span>What breaks</span>
              <span>Layer</span>
            </div>
            <div className="flex-1">
              {SCENARIOS.map((s, i) => (
                <motion.div
                  key={s.name}
                  initial={{ opacity: 0, x: 12 }}
                  whileInView={{ opacity: 1, x: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: 0.25 + i * 0.09 }}
                  className="group grid grid-cols-[1.1fr_2fr_auto] items-center gap-3 border-b border-line-soft px-4 py-3.5 text-[13px] transition-colors hover:bg-raised/60"
                >
                  <span className="flex items-center gap-2 font-medium">
                    <span className="font-mono text-[10.5px] text-faint">{String(i + 1).padStart(2, "0")}</span>
                    {s.name}
                  </span>
                  <span className="text-muted">{s.breaks}</span>
                  <Tag color={s.layer === "build" ? "var(--info)" : s.layer === "runtime" ? "var(--err)" : "var(--warn)"}>{s.layer}</Tag>
                </motion.div>
              ))}
            </div>
            <p className="border-t border-line px-4 py-3.5 text-[12.5px] leading-relaxed text-muted">
              Break the sample app on purpose from the console, run the investigator on each failure, and publish the scorecard —{" "}
              <span className="text-fg">including the misses</span>.
            </p>
          </Spotlight>
        </Reveal>
      </div>

      <div className="mx-auto mt-4 grid max-w-6xl gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {GUARDRAILS.map((g, i) => (
          <Reveal key={g.title} delay={0.05 * i}>
            <Spotlight className="panel h-full p-5">
              <g.icon size={16} className="text-accent" />
              <div className="mt-4 text-[14.5px] font-medium">{g.title}</div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted">{g.body}</p>
            </Spotlight>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
