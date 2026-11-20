"use client";

import { ArrowRight, ArrowUpRight } from "lucide-react";
import { motion, useInView } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CopyButton } from "@/components/ui/primitives";
import { ProviderIcon, providerName, Wordmark } from "@/components/ui/provider";
import { API_DOCS_URL, DOCS_URL, LANDING_ONLY, PRIMARY_CTA, REPO_URL, VERSION } from "@/lib/site";
import { Lines, Rise, Rule, Section } from "./reveal";

// ───────────────────────────── integrations

const PROVIDERS = [
  { id: "vercel", via: "REST", caps: "deploys · build logs · webhooks" },
  { id: "railway", via: "GraphQL", caps: "deploys · build + runtime logs" },
  { id: "github", via: "REST", caps: "commits · diffs · webhooks" },
] as const;
const PLANNED = ["render", "fly", "netlify", "cloudflare", "aws"] as const;

export function Integrations() {
  return (
    <Section
      id="integrations"
      no="04"
      label="Integrations"
      title={["Three today.", "One file each."]}
      lead="One contract. One file per provider."
    >
      <div className="label mb-3">Table 3 — provider manifest</div>
      <div className="border-t border-line">
        {PROVIDERS.map((p, i) => (
          <Rise key={p.id} delay={0.04 * i}>
            <div className="grid grid-cols-[32px_1fr_auto] items-center gap-x-4 border-b border-line py-4 sm:grid-cols-[32px_180px_90px_1fr_110px]">
              <ProviderIcon provider={p.id} size={15} />
              <span className="text-[16px] font-medium">{providerName(p.id)}</span>
              <span className="mono hidden text-[12px] sm:block">{p.via}</span>
              <span className="mono hidden text-[12px] text-muted sm:block">{p.caps}</span>
              <span className="mono text-right text-[11px] uppercase tracking-[0.12em] text-ok">
                <span className="mr-2 inline-block size-1.5 translate-y-[-1px] bg-ok" />
                available
              </span>
            </div>
          </Rise>
        ))}
        <div className="grid grid-cols-[32px_1fr_auto] items-center gap-x-4 border-b border-line py-4 text-faint">
          <span />
          <span className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[15px]">
            {PLANNED.map((id) => (
              <span key={id} className="flex items-center gap-2">
                <ProviderIcon provider={id} size={13} className="opacity-50 grayscale" />
                {providerName(id)}
              </span>
            ))}
          </span>
          <span className="mono text-right text-[11px] uppercase tracking-[0.12em]">planned</span>
        </div>
        <a
          href={`${REPO_URL}/blob/main/docs/adding-a-provider.md`}
          target="_blank"
          rel="noreferrer"
          className="group grid grid-cols-[32px_1fr_auto] items-center gap-x-4 border-b border-line py-5 transition-colors hover:bg-raised"
        >
          <span className="mono text-[15px] text-fg">+</span>
          <span className="text-[16px] font-medium">
            Write your own adapter
          </span>
          <span className="mono flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em] text-muted group-hover:text-fg">
            guide <ArrowUpRight size={12} />
          </span>
        </a>
      </div>
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
  { out: "Demo mode on. Sample deploys seeded.", tone: "muted" },
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
    <div ref={ref} className="mono min-h-[280px] p-5 text-[12.5px] leading-[1.75]">
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
    <Section id="quickstart" no="05" label="Quickstart" title={["Clone. Compose.", "Break something."]} lead="A few minutes on a clean machine.">
      <div className="grid grid-cols-1 border border-line lg:grid-cols-[1.4fr_1fr]">
        <Rise className="min-w-0 border-b border-line bg-surface lg:border-b-0 lg:border-r">
          <div className="label flex h-10 items-center justify-between border-b border-line px-5">
            <span>Terminal</span>
            <CopyButton value={copyAll} label="Copy commands" />
          </div>
          <TerminalDemo />
        </Rise>
        <Rise delay={0.08}>
          <ol>
            {[
              ["Sign in", "Credentials from your .env."],
              ["Connect providers", "Paste a token."],
              ["Break something", "Then click Investigate."],
            ].map(([t, d], i) => (
              <li key={t} className="grid grid-cols-[44px_1fr] border-b border-line px-5 py-6 last:border-b-0">
                <span className="mono pt-1 text-[11.5px] text-faint">5.{i + 1}</span>
                <div>
                  <div className="text-[16px] font-medium">{t}</div>
                  <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{d}</p>
                </div>
              </li>
            ))}
          </ol>
        </Rise>
      </div>
      <Link href={DOCS_URL} className="mono mt-5 inline-flex items-center gap-2 text-[12px] uppercase tracking-[0.12em] text-muted transition-colors hover:text-fg">
        Full setup guide <ArrowRight size={13} />
      </Link>
    </Section>
  );
}

// ───────────────────────────── closing statement + colophon

export function Footer() {
  return (
    <footer>
      <Rule />
      <div className="mx-auto max-w-[1360px] px-5 py-20 sm:px-8 lg:py-28">
        <h2 className="display text-[clamp(52px,11vw,168px)]">
          <Lines lines={["The next red deploy", <span key="e">explains itself<span className="text-[var(--signal)]">.</span></span>]} />
        </h2>
        <Rise delay={0.2} className="mt-10 flex flex-wrap items-stretch gap-3">
          <Link href={PRIMARY_CTA.href} className="group flex h-12 items-center gap-3 bg-fg px-6 text-[15px] font-medium text-bg transition-opacity hover:opacity-85">
            {PRIMARY_CTA.label} <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
          </Link>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="flex h-12 items-center gap-3 border border-line px-6 text-[15px] font-medium transition-colors hover:bg-raised">
            <ProviderIcon provider="github" size={15} /> Source on GitHub
          </a>
        </Rise>
      </div>

      <div className="border-t border-line">
        <div className="label mx-auto grid max-w-[1360px] gap-y-4 px-5 py-6 sm:grid-cols-[1fr_auto] sm:px-8">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Wordmark className="normal-case tracking-normal" />
            <span>v{VERSION}</span>
            <span>open source</span>
            <span>built in public</span>
          </div>
          <nav className="flex flex-wrap gap-x-6 gap-y-2">
            <Link href={DOCS_URL} className="hover:text-fg">Docs</Link>
            {!LANDING_ONLY && <Link href="/console" className="hover:text-fg">Console</Link>}
            {!LANDING_ONLY && <a href={API_DOCS_URL} className="hover:text-fg">API reference</a>}
            <a href="/#integrations" className="hover:text-fg">Integrations</a>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:text-fg">GitHub</a>
          </nav>
        </div>
      </div>
    </footer>
  );
}
