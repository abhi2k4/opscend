"use client";

import { LevelBadge } from "@/components/ui/primitives";
import { Sherlog } from "@/components/ui/sherlog";
import type { LogLevel } from "@/lib/types";
import { Rise, Section } from "./reveal";

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
  { name: "Bad env var", breaks: "Renamed secret", layer: "runtime" },
  { name: "Syntax error", breaks: "Unclosed tag", layer: "build" },
  { name: "Failing migration", breaks: "Index on a missing column", layer: "release" },
  { name: "Dependency bump", breaks: "Removed API", layer: "build" },
  { name: "Timeout", breaks: "Blocking warm-up", layer: "runtime" },
];

const RULES = [
  ["No write path", "Five read tools. Nothing else."],
  ["Evidence or nothing", "Every claim cites a log line, commit or deploy."],
  ["Bounded runs", "Eight tool calls, then it must answer."],
  ["Allowed to not know", "Inconclusive is a valid report."],
];

export function Investigator() {
  const doubled = [...LOGS, ...LOGS];
  return (
    <Section
      id="investigator"
      no="03"
      label="Investigator"
      title={["It reads the logs.", "Then it shows", "its work."]}
      lead="Every step traced. Every claim cited."
    >
      <Rise className="mb-10 flex items-center gap-5 border-y border-line py-5">
        <Sherlog size={92} className="shrink-0" />
        <div>
          <div className="label">Meet the investigator</div>
          <div className="display mt-2 text-[34px] sm:text-[40px]">Sherlog</div>
          <p className="mt-1.5 max-w-md text-[14px] leading-relaxed text-muted">Reads the logs. Names the commit. Says so when it can&apos;t tell.</p>
        </div>
      </Rise>

      <div className="grid grid-cols-1 border border-line lg:grid-cols-2">
        {/* log wall */}
        <Rise className="min-w-0 border-b border-line lg:border-b-0 lg:border-r">
          <div className="label flex h-10 items-center justify-between border-b border-line px-5">
            <span>Fig. 3 — storefront-api, build + runtime</span>
            <span className="text-[var(--signal)]">4 errors</span>
          </div>
          <div className="mask-fade-y h-[380px] overflow-hidden bg-surface">
            <div className="animate-marquee-y py-2 hover:[animation-play-state:paused]">
              {doubled.map(([lvl, msg], i) => (
                <div key={i} className={`mono flex items-center gap-3 px-5 py-[5px] text-[11.5px] ${lvl === "error" ? "bg-[color-mix(in_oklab,var(--signal)_9%,transparent)]" : ""}`}>
                  <span className="w-16 shrink-0 text-faint">14:25:{String(10 + (i % LOGS.length) * 3).padStart(2, "0")}</span>
                  <LevelBadge level={lvl} />
                  <span className={`truncate ${lvl === "error" ? "text-fg" : "text-muted"}`}>{msg}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-line px-5 py-4">
            <div>
              <div className="text-[14px] font-medium">Deploy failed.</div>
              <div className="mono mt-0.5 text-[11.5px] text-muted">railway · storefront-api · 7c3f2de</div>
            </div>
            <span className="mono flex h-9 items-center bg-fg px-4 text-[12px] uppercase tracking-[0.12em] text-bg">Investigate</span>
          </div>
        </Rise>

        {/* scenario ledger */}
        <Rise delay={0.08} className="flex min-w-0 flex-col">
          <div className="label flex h-10 items-center justify-between border-b border-line px-5">
            <span>Table 1 — scripted failures</span>
            <span>in the repo</span>
          </div>
          <table className="w-full flex-1 text-left text-[13.5px]">
            <tbody>
              {SCENARIOS.map((s, i) => (
                <tr key={s.name} className="border-b border-line align-top transition-colors hover:bg-raised">
                  <td className="mono w-12 py-4 pl-5 text-[11.5px] text-faint">{String(i + 1).padStart(2, "0")}</td>
                  <td className="py-4 pr-4 font-medium">{s.name}</td>
                  <td className="py-4 pr-4 text-muted">{s.breaks}</td>
                  <td className="mono py-4 pr-5 text-right text-[11px] uppercase tracking-[0.12em] text-muted">{s.layer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Rise>
      </div>

      {/* house rules */}
      <div className="mt-14">
        <div className="label mb-3">Table 2 — house rules</div>
        <ol className="grid grid-cols-1 border-t border-line md:grid-cols-2 md:gap-x-10">
          {RULES.map(([title, body], i) => (
            <Rise key={title} delay={0.04 * i}>
              <li className="grid grid-cols-[44px_1fr] border-b border-line py-5">
                <span className="mono pt-1 text-[11.5px] text-faint">3.{i + 1}</span>
                <div>
                  <div className="text-[16px] font-medium">{title}</div>
                  <p className="mt-1.5 max-w-md text-[14px] leading-relaxed text-muted">{body}</p>
                </div>
              </li>
            </Rise>
          ))}
        </ol>
      </div>
    </Section>
  );
}
