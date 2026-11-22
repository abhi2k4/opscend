"use client";

import { ArrowRight, ArrowUpRight } from "lucide-react";
import { motion, useInView } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CopyButton } from "@/components/ui/primitives";
import { ProviderIcon, providerName, Wordmark } from "@/components/ui/provider";
import { Sherlog } from "@/components/ui/sherlog";
import { API_DOCS_URL, DOCS_URL, LANDING_ONLY, PRIMARY_CTA, REPO_URL, VERSION } from "@/lib/site";
import { Lines, Rise, Rule, Section } from "./reveal";

// ───────────────────────────── integrations

const PROVIDERS = ["vercel", "railway", "render", "fly", "netlify", "cloudflare", "aws", "github"] as const;

export function Integrations() {
  return (
    <Section id="integrations" label="Integrations" title={["Works with", "where you deploy."]} lead="Eight platforms today. Each one is a single file, so adding yours is an afternoon.">
      <Rise>
        <ul className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
          {PROVIDERS.map((id) => (
            <li key={id} className="flex flex-col items-center gap-4 bg-bg px-4 py-10 text-fg/85 transition-colors duration-300 hover:bg-surface hover:text-fg">
              <ProviderIcon provider={id} size={30} />
              <span className="text-[15px]">{providerName(id)}</span>
            </li>
          ))}
        </ul>
      </Rise>
      <Rise delay={0.1}>
        <a href={`${REPO_URL}/blob/main/docs/adding-a-provider.md`} target="_blank" rel="noreferrer" className="group mt-8 inline-flex items-center gap-2 text-[15px] text-fg/80 transition-colors hover:text-fg">
          Not on the list? Write your own adapter
          <ArrowUpRight size={14} className="text-muted transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
        </a>
      </Rise>
    </Section>
  );
}

// ───────────────────────────── quickstart

const LINES: { cmd?: string; out?: string; tone?: "ok" | "muted" }[] = [
  { cmd: `git clone ${REPO_URL}.git && cd opscend` },
  { cmd: "cp .env.example .env   # add GROQ_API_KEY" },
  { cmd: "docker compose up" },
  { out: "[ok] postgres   healthy", tone: "ok" },
  { out: "[ok] redis      healthy", tone: "ok" },
  { out: "[ok] api        http://localhost:8000/api/docs", tone: "ok" },
  { out: "[ok] worker     polling every 60s", tone: "ok" },
  { out: "[ok] web        http://localhost:3000", tone: "ok" },
];

function TerminalDemo() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-25% 0px" });
  const [line, setLine] = useState(0);
  const [chars, setChars] = useState(0);

  useEffect(() => {
    if (!inView || line >= LINES.length) return;
    const cur = LINES[line];
    if (cur.cmd && chars < cur.cmd.length) {
      const t = setTimeout(() => setChars((c) => c + 2), 22);
      return () => clearTimeout(t);
    }
    const t = setTimeout(
      () => {
        setLine((l) => l + 1);
        setChars(0);
      },
      cur.cmd ? 420 : 170,
    );
    return () => clearTimeout(t);
  }, [inView, line, chars]);

  return (
    <div ref={ref} className="mono min-h-[250px] p-5 text-[13.5px] leading-[1.8] sm:p-6">
      {LINES.slice(0, line + 1).map((l, i) => {
        if (l.cmd) {
          const text = i === line ? l.cmd.slice(0, chars) : l.cmd;
          const [main, comment] = text.split("   #");
          return (
            <div key={i} className="flex gap-3">
              <span className="select-none text-faint">$</span>
              <span className="break-all">
                {main}
                {comment !== undefined && <span className="text-faint">   #{comment}</span>}
                {i === line && <span className="ml-0.5 inline-block h-3.5 w-2 translate-y-0.5 animate-caret bg-fg" />}
              </span>
            </div>
          );
        }
        return (
          <motion.div key={i} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={l.tone === "ok" ? "text-ok" : "mt-2 text-muted"}>
            {l.out}
          </motion.div>
        );
      })}
    </div>
  );
}

export function Quickstart() {
  const copyAll = LINES.filter((l) => l.cmd)
    .map((l) => l.cmd!.split("   #")[0])
    .join("\n");
  return (
    <Section id="quickstart" label="Quickstart" title={["Running in", "three commands."]} lead="No account and no cloud. It runs on your machine with Docker, and starts with demo data so there is something to look at.">
      <Rise className="max-w-3xl border border-line bg-surface">
        <div className="flex h-11 items-center justify-between border-b border-line px-5">
          <span className="label">Terminal</span>
          <CopyButton value={copyAll} label="Copy commands" />
        </div>
        <TerminalDemo />
      </Rise>
      <Rise delay={0.1}>
        <Link href={DOCS_URL} className="group mt-8 inline-flex items-center gap-2 text-[15px] text-fg/80 transition-colors hover:text-fg">
          Read the full setup guide <ArrowRight size={14} className="text-muted transition-transform group-hover:translate-x-1" />
        </Link>
      </Rise>
    </Section>
  );
}

// ───────────────────────────── closing statement + colophon

export function Footer() {
  return (
    <footer>
      <Rule />
      <div className="mx-auto grid max-w-[1120px] grid-cols-1 items-end gap-10 px-6 py-24 sm:px-8 md:grid-cols-[1fr_auto] lg:py-36">
        <div>
          <h2 className="display text-[clamp(44px,7.4vw,104px)]">
            <Lines lines={["The next red deploy", <span key="e">explains itself<span className="text-[var(--signal)]">.</span></span>]} />
          </h2>
          <Rise delay={0.2} className="mt-10 flex flex-wrap items-center gap-x-7 gap-y-4">
            <Link href={PRIMARY_CTA.href} className="group flex h-12 items-center gap-3 bg-fg px-6 text-[15px] font-medium text-bg transition-opacity hover:opacity-85">
              {PRIMARY_CTA.label} <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
            </Link>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 text-[15px] text-fg/80 transition-colors hover:text-fg">
              <ProviderIcon provider="github" size={16} /> View the source
            </a>
          </Rise>
        </div>
        <Rise delay={0.3} className="hidden md:block">
          <Sherlog size={170} />
        </Rise>
      </div>

      <div className="border-t border-line-soft">
        <div className="mx-auto flex max-w-[1120px] flex-wrap items-center justify-between gap-x-8 gap-y-4 px-6 py-7 text-[13.5px] text-muted sm:px-8">
          <div className="flex items-center gap-4">
            <Wordmark />
            <span>v{VERSION} · MIT</span>
          </div>
          <nav className="flex flex-wrap gap-x-7 gap-y-2">
            <Link href={DOCS_URL} className="transition-colors hover:text-fg">Docs</Link>
            {!LANDING_ONLY && <Link href="/console" className="transition-colors hover:text-fg">Console</Link>}
            {!LANDING_ONLY && <a href={API_DOCS_URL} className="transition-colors hover:text-fg">API reference</a>}
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="transition-colors hover:text-fg">GitHub</a>
          </nav>
        </div>
      </div>
    </footer>
  );
}
