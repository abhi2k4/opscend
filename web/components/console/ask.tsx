"use client";

import { Activity, Boxes, ChevronRight, FileSearch, GitCommitHorizontal, Rocket, ScrollText, Siren, Wrench } from "lucide-react";
import Link from "next/link";
import { Fragment, useState, type ReactNode } from "react";
import { useNow } from "@/components/console/deploys";
import { Dot, Spinner } from "@/components/ui/primitives";
import { cn, duration } from "@/lib/format";
import type { ChatChart, ChatCitation, ChatCitationType, ChatMessage, ChatStep } from "@/lib/types";
import { ChatChartView } from "./chat-chart";

// ───────────────────────────── citations

const CITATION_ICON: Record<ChatCitationType, typeof Rocket> = {
  deploy: Rocket,
  log: ScrollText,
  commit: GitCommitHorizontal,
  incident: Siren,
  investigation: FileSearch,
  service: Boxes,
};

function citationHref(c: ChatCitation): { href: string; external: boolean } | null {
  switch (c.type) {
    case "deploy":
      return { href: `/console/deployments/${c.ref}`, external: false };
    case "log":
      return c.deployment_id ? { href: `/console/deployments/${c.deployment_id}?log=${c.ref}`, external: false } : null;
    case "commit":
      if (c.url) return { href: c.url, external: true };
      return c.deployment_id ? { href: `/console/deployments/${c.deployment_id}?tab=diff`, external: false } : null;
    case "incident":
      return { href: "/console/incidents", external: false };
    case "investigation":
      return { href: `/console/investigations/${c.ref}`, external: false };
    case "service":
      return { href: "/console/timeline", external: false };
  }
}

export function CitationChip({ citation }: { citation: ChatCitation }) {
  const Icon = CITATION_ICON[citation.type];
  const target = citationHref(citation);
  const title = citation.detail ?? `${citation.type} ${citation.ref}`;
  const body = (
    <>
      <Icon size={10.5} className="shrink-0 text-faint" />
      <span className="truncate">{citation.label}</span>
    </>
  );
  const cls =
    "mx-0.5 inline-flex max-w-[240px] translate-y-[-1px] items-center gap-1 rounded-[4px] border border-line bg-raised px-1.5 align-middle font-mono text-[11px] leading-[18px] text-muted transition-colors";
  if (!target) return <span className={cls} title={title}>{body}</span>;
  if (target.external) {
    return (
      <a href={target.href} target="_blank" rel="noreferrer" className={cn(cls, "hover:border-[var(--line-strong)] hover:text-fg")} title={title}>
        {body}
      </a>
    );
  }
  return (
    <Link href={target.href} className={cn(cls, "hover:border-[var(--line-strong)] hover:text-fg")} title={title}>
      {body}
    </Link>
  );
}

// ───────────────────────────── answer text
// A deliberately small renderer for what the prompt asks the model to write:
// paragraphs, bullet and numbered lists, fenced code, `code`, **bold** and
// citation markers. Everything renders as React text, never as HTML.

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[(?:deploy|log|commit|incident|investigation|service):[^\]\s]+\])/g;
const MARKER = /^\[(deploy|log|commit|incident|investigation|service):([^\]\s]+)\]$/;

function Inline({ text, citations }: { text: string; citations: Map<string, ChatCitation> }) {
  const parts = text.split(INLINE);
  return (
    <>
      {parts.map((part, i) => {
        if (!part) return null;
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
          return (
            <code key={i} className="rounded-[4px] border border-line-soft bg-bg px-1 py-px font-mono text-[12px] text-fg">
              {part.slice(1, -1)}
            </code>
          );
        }
        if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
          return (
            <strong key={i} className="font-medium text-fg">
              <Inline text={part.slice(2, -2)} citations={citations} />
            </strong>
          );
        }
        const marker = MARKER.exec(part);
        if (marker) {
          const citation = citations.get(`${marker[1]}:${marker[2]}`);
          return citation ? <CitationChip key={i} citation={citation} /> : null;
        }
        return <Fragment key={i}>{part}</Fragment>;
      })}
    </>
  );
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul" | "ol"; items: string[] } | { kind: "code"; text: string } | { kind: "chart"; id: string };

function toBlocks(content: string): Block[] {
  const blocks: Block[] = [];
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const body: string[] = [];
      for (i++; i < lines.length && !lines[i].trim().startsWith("```"); i++) body.push(lines[i]);
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const chart = /^\s*\[chart:([^\]\s]+)\]\s*$/.exec(line);
    if (chart) {
      blocks.push({ kind: "chart", id: chart[1] });
      continue;
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];
    if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      const text = (bullet ?? numbered)![1];
      if (last?.kind === kind) last.items.push(text);
      else blocks.push({ kind, items: [text] });
    } else if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] });
    } else if (last?.kind === "p") {
      last.lines.push(line.replace(/^#+\s*/, ""));
    } else if ((last?.kind === "ul" || last?.kind === "ol") && /^\s{2,}\S/.test(line)) {
      last.items[last.items.length - 1] += ` ${line.trim()}`;
    } else {
      blocks.push({ kind: "p", lines: [line.replace(/^#+\s*/, "")] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : true));
}

export function AnswerText({ content, citations, charts = [] }: { content: string; citations: ChatCitation[]; charts?: ChatChart[] }) {
  const byKey = new Map(citations.map((c) => [`${c.type}:${c.ref}`, c]));
  const chartById = new Map(charts.map((c) => [c.id, c]));
  return (
    <div className="space-y-2.5 text-[13.5px] leading-[1.7] text-fg/90">
      {toBlocks(content).map((block, i) => {
        if (block.kind === "chart") {
          const chart = chartById.get(block.id);
          return chart ? <ChatChartView key={i} chart={chart} /> : null;
        }
        if (block.kind === "code") {
          return (
            <pre key={i} className="code overflow-x-auto rounded-md border border-line bg-bg p-3 text-muted">
              {block.text}
            </pre>
          );
        }
        if (block.kind === "p") {
          return (
            <p key={i}>
              {block.lines.map((line, j) => (
                <Fragment key={j}>
                  {j > 0 && <br />}
                  <Inline text={line} citations={byKey} />
                </Fragment>
              ))}
            </p>
          );
        }
        const List = block.kind === "ul" ? "ul" : "ol";
        return (
          <List key={i} className={cn("space-y-1 pl-5", block.kind === "ul" ? "list-disc marker:text-faint" : "list-decimal marker:font-mono marker:text-[11.5px] marker:text-faint")}>
            {block.items.map((item, j) => (
              <li key={j} className="pl-1">
                <Inline text={item} citations={byKey} />
              </li>
            ))}
          </List>
        );
      })}
    </div>
  );
}

// ───────────────────────────── tool steps

function stepArgs(input: ChatStep["input"]): string {
  if (!input) return "";
  return Object.entries(input)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ");
}

export function StepList({ steps, live }: { steps: ChatStep[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  const errors = steps.filter((s) => s.status === "error").length;
  const shown = open || live;
  return (
    <div className="mb-3">
      <button onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 font-mono text-[11px] text-faint hover:text-muted" aria-expanded={shown}>
        <ChevronRight size={11} className={cn("transition-transform", shown && "rotate-90")} />
        <Wrench size={10.5} />
        {steps.length} {steps.length === 1 ? "query" : "queries"}
        {errors > 0 && <span className="text-err">· {errors} failed</span>}
      </button>
      {shown && (
        <ol className="mt-2 space-y-1 border-l border-line-soft pl-3">
          {steps.map((step, i) => (
            <li key={i} className="font-mono text-[11px] leading-[1.6]">
              <div className="flex items-center gap-2">
                {step.status === "running" ? (
                  <Spinner className="size-2.5 text-muted" />
                ) : (
                  <Dot color={step.status === "ok" ? "var(--ok)" : "var(--err)"} className="scale-75" />
                )}
                <span className="text-muted">{step.name}</span>
                <span className="min-w-0 truncate text-faint">{stepArgs(step.input)}</span>
                {step.duration_ms != null && <span className="ml-auto shrink-0 text-faint">{duration(step.duration_ms)}</span>}
              </div>
              {step.summary && <div className="truncate pl-[18px] text-faint">{step.summary}</div>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ───────────────────────────── messages

export function MessageView({ message }: { message: ChatMessage }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-lg border border-line bg-raised px-3.5 py-2.5 text-[13.5px] leading-[1.6]">{message.content}</div>
      </div>
    );
  }
  const live = message.status === "pending" || message.status === "running";
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-md border border-line bg-surface text-muted">
        <Activity size={12} />
      </div>
      <div className="min-w-0 flex-1">
        <StepList steps={message.steps} live={live} />
        {live && <Thinking message={message} />}
        {message.status === "done" && <AnswerText content={message.content} citations={message.citations} charts={message.charts} />}
        {message.status === "failed" && (
          <div className="rounded-md border border-err/30 bg-err/5 px-3 py-2 text-[12.5px] text-err">
            Could not answer: {message.error ?? "unknown error"}
          </div>
        )}
      </div>
    </div>
  );
}

function Thinking({ message }: { message: ChatMessage }) {
  const now = useNow(1000);
  const waited = (now - Date.parse(message.created_at)) / 1000;
  let label = message.steps.length ? "Looking through the data…" : "Reading the question…";
  // Still queued: the job has not reached a worker (or the worker is busy or down).
  if (message.status === "pending" && waited > 10) label = "Waiting for a worker to pick this up…";
  else if (waited > 20) label = "Still working: the model API may be rate limiting…";
  return (
    <div className="flex items-center gap-2 font-mono text-[11.5px] text-muted">
      <Spinner className="size-3" />
      {label}
      {waited > 5 && <span className="text-faint">{Math.round(waited)}s</span>}
    </div>
  );
}

export function Suggestions({ onPick, children, demo }: { onPick: (q: string) => void; children?: ReactNode; demo?: boolean }) {
  const questions = [
    "Which services had failed deploys this week?",
    "Why did the last failed deploy fail?",
    "What's the failure rate and recovery time per service?",
    // The sample data has no connection errors, so the demo searches for something it does have.
    demo ? "Search the logs for STRIPE_WEBHOOK_SECRET" : "Search the logs for ECONNREFUSED",
    "Are any services unhealthy right now?",
    "What did the most recent commits change?",
  ];
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-4 py-12 text-center">
      {children}
      <div data-tour="ask" className="mt-6 grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {questions.map((q) => (
          <button key={q} onClick={() => onPick(q)} className="rounded-lg border border-line bg-surface px-3 py-2.5 text-left text-[12.5px] text-muted transition-colors hover:border-[var(--line-strong)] hover:text-fg">
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
