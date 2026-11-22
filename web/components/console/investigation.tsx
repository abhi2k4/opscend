"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUpRight, Bot, ChevronRight, CircleHelp, FileCheck2, GitCommitHorizontal, HeartPulse, Lightbulb, Rocket, ScrollText, ThumbsDown, ThumbsUp, Wrench } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { mutate } from "swr";
import { ConfidenceMeter, CopyButton, Mono, Spinner, Tag } from "@/components/ui/primitives";
import { Sherlog } from "@/components/ui/sherlog";
import { api } from "@/lib/api";
import { cn, compact, duration, shortSha } from "@/lib/format";
import type { EvidenceRef, Investigation, InvestigationReport, InvestigationStep } from "@/lib/types";

const STEP = {
  llm: { color: "var(--info)", icon: Bot, label: "llm" },
  tool: { color: "var(--accent)", icon: Wrench, label: "tool" },
  report: { color: "var(--ok)", icon: FileCheck2, label: "report" },
} as const;

/** One-line preview of a tool call's arguments, e.g. `kind=build limit=200`. */
function argPreview(input: Record<string, unknown> | null): string {
  if (!input) return "";
  return Object.entries(input)
    .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v))
    .slice(0, 3)
    .map(([k, v]) => `${k}=${String(v).length > 16 ? `${String(v).slice(0, 12)}…` : v}`)
    .join(" ");
}

// ───────────────────────────── trace

export function TraceView({ inv }: { inv: Investigation }) {
  const running = inv.status === "running" || inv.status === "queued";
  const [open, setOpen] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [running]);

  const { t0, total } = useMemo(() => {
    if (inv.steps.length === 0) return { t0: 0, total: 1 };
    const start = Math.min(...inv.steps.map((s) => new Date(s.started_at).getTime()));
    const end = Math.max(...inv.steps.map((s) => new Date(s.started_at).getTime() + (s.duration_ms ?? (running ? Math.max(0, now - new Date(s.started_at).getTime()) : 0))));
    return { t0: start, total: Math.max(1, end - start) };
  }, [inv.steps, running, now]);

  return (
    <div>
      {/* root span */}
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(80px,38%)_58px] items-center gap-3 border-b border-line px-4 py-2.5 font-mono text-[12px]">
        <span className="flex items-center gap-2 truncate">
          <span className="text-faint">agent run:</span> <span className="text-fg">&apos;investigator&apos;</span>
          <span className="rounded-sm bg-raised px-1 text-[10.5px] text-muted">{inv.steps.length}</span>
        </span>
        <span className="relative h-1.5 overflow-hidden rounded-full bg-line">
          <span className={cn("absolute inset-0 rounded-full bg-fg/60", running && "animate-pulse")} />
        </span>
        <span className="text-right text-muted">{duration(inv.duration_ms ?? (running ? total : null))}</span>
      </div>

      <div className="py-1">
        <AnimatePresence initial={false}>
          {inv.steps.map((s) => (
            <SpanRow key={s.id} s={s} t0={t0} total={total} now={now} open={open === s.id} onToggle={() => setOpen(open === s.id ? null : s.id)} />
          ))}
        </AnimatePresence>
        {running && (
          <div className="flex items-center gap-2.5 px-4 py-2.5 font-mono text-[11.5px] text-muted">
            <Spinner className="text-accent" /> {inv.status === "queued" ? "queued — waiting for the worker" : "thinking…"}
          </div>
        )}
        {!running && inv.steps.length === 0 && <div className="px-4 py-8 text-center text-[13px] text-muted">No steps were recorded.</div>}
      </div>
    </div>
  );
}

function SpanRow({ s, t0, total, now, open, onToggle }: { s: InvestigationStep; t0: number; total: number; now: number; open: boolean; onToggle: () => void }) {
  const meta = STEP[s.type] ?? STEP.tool;
  const start = new Date(s.started_at).getTime();
  const live = s.status === "running";
  const ms = s.duration_ms ?? (live ? Math.max(0, now - start) : 0);
  const left = ((start - t0) / total) * 100;
  const width = Math.max(1.5, (ms / total) * 100);
  const color = s.status === "error" ? "var(--err)" : meta.color;

  return (
    <motion.div layout="position" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.25 }}>
      <button
        onClick={onToggle}
        aria-expanded={open}
        className={cn("grid w-full grid-cols-[minmax(0,1fr)_minmax(80px,38%)_58px] items-center gap-3 px-4 py-[7px] text-left font-mono text-[12px] transition-colors hover:bg-raised/60", open && "bg-raised/60")}
      >
        <span className="flex min-w-0 items-center gap-2" style={{ paddingLeft: s.type === "tool" ? 18 : 0 }}>
          <ChevronRight size={11} className={cn("shrink-0 text-faint transition-transform", open && "rotate-90")} />
          <meta.icon size={12} className="shrink-0" style={{ color }} />
          <span className="shrink-0 text-faint">{meta.label}:</span>
          <span className={cn("text-fg", s.type === "tool" ? "shrink-0" : "truncate")}>{s.name}</span>
          {s.type === "tool" && <span className="hidden truncate text-faint xl:inline">{argPreview(s.input)}</span>}
        </span>
        <span className="relative h-1.5 rounded-full bg-line/50">
          <span
            className={cn("absolute inset-y-0 rounded-full transition-[width] duration-100", live && "animate-pulse")}
            style={{ left: `${Math.min(98.5, left)}%`, width: `${Math.min(100 - Math.min(98.5, left), width)}%`, background: color }}
          />
        </span>
        <span className="text-right tabular-nums text-muted">{live ? <span className="text-accent">{duration(ms)}</span> : duration(s.duration_ms)}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mx-4 mb-2 mt-1 space-y-3 rounded-lg border border-line bg-bg/60 p-3">
              <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px] text-muted">
                <span>status <span style={{ color }}>{s.status}</span></span>
                <span>duration <span className="text-fg">{duration(s.duration_ms)}</span></span>
                {s.tokens != null && <span>tokens <span className="text-fg">{s.tokens}</span></span>}
                <span>step <span className="text-fg">{s.index}</span></span>
              </div>
              {s.input && Object.keys(s.input).length > 0 && (
                <div>
                  <div className="label-mono mb-1 flex items-center justify-between">
                    input <CopyButton value={JSON.stringify(s.input, null, 2)} />
                  </div>
                  <pre className="code max-h-48 overflow-auto whitespace-pre-wrap break-all text-[11.5px] text-fg/80">{JSON.stringify(s.input, null, 2)}</pre>
                </div>
              )}
              {s.output_summary && (
                <div>
                  <div className="label-mono mb-1">output</div>
                  <pre className="code max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11.5px] text-fg/80">{s.output_summary}</pre>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ───────────────────────────── report

const EVIDENCE = {
  log: { icon: ScrollText, color: "var(--err)" },
  commit: { icon: GitCommitHorizontal, color: "var(--github)" },
  deploy: { icon: Rocket, color: "var(--info)" },
  health: { icon: HeartPulse, color: "var(--warn)" },
} as const;

function evidenceHref(e: EvidenceRef, inv: Investigation): string | null {
  switch (e.type) {
    case "log":
      return `/console/deployments/${e.deployment_id}?log=${encodeURIComponent(e.ref)}`;
    case "commit":
      return inv.deployment_id ? `/console/deployments/${inv.deployment_id}?tab=diff` : null;
    case "deploy":
      return `/console/deployments/${e.ref}`;
    default:
      return null;
  }
}

function EvidenceItem({ e, inv, i }: { e: EvidenceRef; inv: Investigation; i: number }) {
  const meta = EVIDENCE[e.type] ?? EVIDENCE.log;
  const href = evidenceHref(e, inv);
  const body = (
    <>
      <span className="mt-px grid size-6 shrink-0 place-items-center rounded-md border border-line bg-raised">
        <meta.icon size={12} style={{ color: meta.color }} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <Tag color={meta.color}>{e.type}</Tag>
          <span className="truncate font-mono text-[11.5px] text-muted">{e.type === "commit" ? shortSha(e.ref) : e.ref}</span>
        </span>
        <span className="mt-1.5 block break-words font-mono text-[12px] leading-relaxed text-fg/90">{e.quote}</span>
      </span>
      {href && <ArrowUpRight size={13} className="shrink-0 text-faint transition-colors group-hover:text-accent" />}
    </>
  );
  const cls = "group flex items-start gap-3 rounded-lg border border-line bg-bg/50 p-3 transition-colors";
  return (
    <motion.li initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.07 }}>
      {href ? (
        <Link href={href} className={cn(cls, "hover:border-[var(--line-strong)] hover:bg-raised/50")}>
          {body}
        </Link>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </motion.li>
  );
}

export function ReportView({ inv }: { inv: Investigation }) {
  const r: InvestigationReport | null = inv.report;

  if (inv.status === "failed") {
    return (
      <div className="p-5">
        <Tag color="var(--err)">run failed</Tag>
        <p className="mt-3 break-words font-mono text-[12.5px] leading-relaxed text-fg/90">{inv.error ?? "The investigator stopped without a report."}</p>
        <p className="mt-3 text-[13px] text-muted">The steps it completed are still in the trace. Check the model id and key in your .env, then re-run from the deploy page.</p>
      </div>
    );
  }

  if (!r) {
    const last = inv.steps[inv.steps.length - 1];
    return (
      <div className="p-5">
        <div className="flex items-center gap-3 text-[13px] text-muted">
          <Sherlog size={46} className="-my-2 shrink-0" title="Sherlog is investigating" />
          {last ? (
            <span>
              {last.type === "tool" ? "Calling" : "Running"} <span className="font-mono text-fg">{last.name}</span>
            </span>
          ) : (
            "Sherlog is picking up the trail"
          )}
        </div>
        <div className="mt-6 space-y-3">
          {[92, 100, 74].map((w) => (
            <div key={w} className="skeleton h-4" style={{ width: `${w}%` }} />
          ))}
          <div className="skeleton mt-6 h-16" />
          <div className="skeleton h-16" />
        </div>
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="label-mono flex items-center gap-2">
          {r.inconclusive ? <CircleHelp size={13} className="text-warn" /> : null}
          {r.inconclusive ? "Inconclusive" : "Likely cause"}
        </span>
        <ConfidenceMeter confidence={r.confidence} />
      </div>
      <p className="mt-3 text-[15.5px] leading-relaxed">{r.likely_cause}</p>

      {r.culprit_commit_sha && (
        <div className="mt-4 flex items-center gap-2.5 rounded-lg border border-line bg-bg/50 px-3 py-2 text-[12.5px]">
          <GitCommitHorizontal size={14} className="text-faint" />
          <span className="text-muted">Named commit</span>
          <Mono value={r.culprit_commit_sha} display={shortSha(r.culprit_commit_sha)} className="rounded-sm bg-raised px-1.5 py-0.5 text-accent" />
          {inv.deployment_id && (
            <Link href={`/console/deployments/${inv.deployment_id}?tab=diff`} className="ml-auto font-mono text-[11px] text-muted hover:text-fg">
              view diff →
            </Link>
          )}
        </div>
      )}

      {r.inconclusive && r.missing && (
        <div className="mt-4 rounded-lg border border-warn/30 bg-warn/[0.06] p-3 text-[13px] leading-relaxed">
          <div className="label-mono mb-1 text-warn">What was missing</div>
          {r.missing}
        </div>
      )}

      <div className="label-mono mb-2 mt-6 flex items-center justify-between">
        <span>Evidence</span>
        <span className="text-faint">{r.evidence.length} cited</span>
      </div>
      {r.evidence.length === 0 ? (
        <p className="text-[13px] text-muted">No evidence survived verification.</p>
      ) : (
        <ul className="space-y-2">
          {r.evidence.map((e, i) => (
            <EvidenceItem key={`${e.type}-${e.ref}-${i}`} e={e} inv={inv} i={i} />
          ))}
        </ul>
      )}

      {r.suggested_fix && (
        <div className="mt-6 rounded-lg border border-accent/25 bg-accent/[0.05] p-4">
          <div className="label-mono mb-1.5 flex items-center gap-1.5 text-accent">
            <Lightbulb size={12} /> Suggested fix
          </div>
          <p className="text-[13.5px] leading-relaxed text-fg/90">{r.suggested_fix}</p>
          <p className="mt-2 font-mono text-[10.5px] uppercase tracking-wider text-faint">Opscend is read-only. Apply this yourself.</p>
        </div>
      )}

      <Feedback inv={inv} />
    </motion.div>
  );
}

/** Thumbs up or down on a finished report, with an optional note on what was wrong. */
function Feedback({ inv }: { inv: Investigation }) {
  const rating = inv.feedback?.rating ?? null;
  const [note, setNote] = useState(inv.feedback?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(next: "up" | "down" | null, text?: string) {
    setBusy(true);
    setError(null);
    try {
      const saved = await api<Investigation>(`/investigations/${inv.id}/feedback`, { method: "PUT", json: { rating: next, note: text ?? null } });
      await mutate(`/investigations/${inv.id}`, saved, { revalidate: false });
      void mutate("/investigations/stats");
      if (!next) setNote("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  const choice = (value: "up" | "down", Icon: typeof ThumbsUp, label: string, tone: string) => (
    <button
      type="button"
      aria-pressed={rating === value}
      aria-label={label}
      title={rating === value ? "Click again to clear" : label}
      disabled={busy}
      // Clicking the chosen thumb again clears the rating.
      onClick={() => send(rating === value ? null : value, value === "down" ? note.trim() || undefined : undefined)}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12px] transition-colors disabled:opacity-50",
        rating === value ? tone : "border-line bg-raised text-muted hover:border-[var(--line-strong)] hover:text-fg",
      )}
    >
      <Icon size={12} /> {value === "up" ? "Right" : "Wrong"}
    </button>
  );

  return (
    <div className="mt-6 border-t border-line pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="label-mono mr-1">Was this right?</span>
        {choice("up", ThumbsUp, "The report was right", "border-ok/40 bg-ok/[0.08] text-ok")}
        {choice("down", ThumbsDown, "The report was wrong", "border-err/40 bg-err/[0.08] text-err")}
        {rating && <span className="font-mono text-[11px] text-faint">saved</span>}
        {error && <span className="text-[12px] text-err">{error}</span>}
      </div>
      {rating === "down" && (
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void send("down", note.trim() || undefined);
          }}
        >
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            placeholder="What was the real cause? (optional)"
            aria-label="What was the real cause?"
            className="h-8 min-w-0 flex-1 rounded-md border border-line bg-bg/50 px-2.5 text-[12.5px] outline-none placeholder:text-faint focus:border-[var(--line-strong)]"
          />
          <button type="submit" disabled={busy || note.trim() === (inv.feedback?.note ?? "")} className="h-8 rounded-md border border-line bg-raised px-3 text-[12px] hover:border-[var(--line-strong)] disabled:opacity-40">
            Save note
          </button>
        </form>
      )}
    </div>
  );
}

export function RunMeta({ inv }: { inv: Investigation }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
      <span>{inv.model}</span>
      <span>{inv.steps.length} steps</span>
      <span>{compact(inv.tokens_used)} tokens</span>
      <span>{duration(inv.duration_ms)}</span>
    </div>
  );
}
