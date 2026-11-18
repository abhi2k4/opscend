"use client";

import { ArrowRight, ArrowUpRight, Plus } from "lucide-react";
import { motion, useInView } from "motion/react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ButtonLink, CopyButton, Spotlight, Tag } from "@/components/ui/primitives";
import { ProviderIcon, providerName, Wordmark } from "@/components/ui/provider";
import { API_DOCS_URL, REPO_URL } from "@/lib/site";
import { Reveal, SectionHeading } from "./reveal";

// ───────────────────────────── integrations

const PROVIDERS = [
  { id: "vercel", state: "available", caps: ["deploys", "build logs", "webhooks"] },
  { id: "railway", state: "available", caps: ["deploys", "build logs", "runtime logs"] },
  { id: "github", state: "available", caps: ["commits", "diffs", "webhooks"] },
  { id: "render", state: "planned", caps: [] },
  { id: "fly", state: "planned", caps: [] },
  { id: "netlify", state: "planned", caps: [] },
  { id: "cloudflare", state: "planned", caps: [] },
  { id: "aws", state: "planned", caps: [] },
] as const;

export function Integrations() {
  return (
    <section id="integrations" className="relative px-4 py-28">
      <SectionHeading eyebrow="Integrations" lead="Three today." rest="The adapter contract is the roadmap: one file and one registry line per provider." />
      <div className="mx-auto mt-14 grid max-w-6xl gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {PROVIDERS.map((p, i) => (
          <Reveal key={p.id} delay={0.04 * i}>
            <Spotlight className={`panel flex h-full min-h-[132px] flex-col p-4 ${p.state === "planned" ? "opacity-60" : ""}`}>
              <div className="flex items-center justify-between">
                <span className="grid size-9 place-items-center rounded-lg border border-line bg-raised">
                  <ProviderIcon provider={p.id} size={16} />
                </span>
                {p.state === "available" ? <Tag color="var(--ok)">available</Tag> : <Tag>planned</Tag>}
              </div>
              <div className="mt-4 text-[14.5px] font-medium">{providerName(p.id)}</div>
              <div className="mt-1 font-mono text-[11px] text-muted">{p.caps.length ? p.caps.join(" · ") : "adapter not written yet"}</div>
            </Spotlight>
          </Reveal>
        ))}
        <Reveal delay={0.3} className="sm:col-span-2 lg:col-span-4">
          <Spotlight className="panel flex flex-col items-start justify-between gap-4 border-dashed p-5 sm:flex-row sm:items-center">
            <div className="flex items-center gap-4">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-dashed border-accent/50 text-accent">
                <Plus size={16} />
              </span>
              <div>
                <div className="text-[14.5px] font-medium">Write your own adapter</div>
                <div className="mt-0.5 text-[13px] text-muted">
                  Implement <code className="font-mono text-fg">ProviderAdapter</code>, declare its capabilities, register it. The console picks it up from the
                  catalog endpoint.
                </div>
              </div>
            </div>
            <a href={`${REPO_URL}/blob/main/docs/adding-a-provider.md`} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1.5 font-mono text-[12px] text-accent hover:underline">
              docs/adding-a-provider.md <ArrowUpRight size={12} />
            </a>
          </Spotlight>
        </Reveal>
      </div>
    </section>
  );
}

// ───────────────────────────── quickstart

const LINES: { cmd?: string; out?: string; tone?: "ok" | "muted" }[] = [
  { cmd: `git clone ${REPO_URL}.git && cd opscend` },
  { cmd: "cp .env.example .env   # add GROQ_API_KEY" },
  { cmd: "docker compose up" },
  { out: "✔ postgres   healthy", tone: "ok" },
  { out: "✔ redis      healthy", tone: "ok" },
  { out: "✔ api        http://localhost:8000/api/docs", tone: "ok" },
  { out: "✔ worker     polling every 30s", tone: "ok" },
  { out: "✔ web        http://localhost:3000", tone: "ok" },
  { out: "Demo mode on: sample deploys seeded. Connect a provider in Integrations.", tone: "muted" },
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
    <div ref={ref} className="code min-h-[268px] p-5 text-[12.5px]">
      {LINES.slice(0, line + 1).map((l, i) => {
        if (l.cmd) {
          const text = i === line ? l.cmd.slice(0, chars) : l.cmd;
          const [main, comment] = text.split("   #");
          return (
            <div key={i} className="flex gap-2">
              <span className="select-none text-accent">$</span>
              <span className="break-all">
                {main}
                {comment !== undefined && <span className="text-faint">   #{comment}</span>}
                {i === line && <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-caret bg-fg" />}
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
    <section id="quickstart" className="relative px-4 py-28">
      <SectionHeading eyebrow="Quickstart" lead="Clone. Compose. Break something." rest="Running on a clean machine in under five minutes." />
      <div className="mx-auto mt-14 grid max-w-6xl gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Reveal>
          <div className="panel overflow-hidden">
            <div className="flex h-10 items-center justify-between border-b border-line px-4">
              <span className="label-mono">Terminal</span>
              <CopyButton value={copyAll} label="Copy commands" />
            </div>
            <TerminalDemo />
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <div className="panel flex h-full flex-col divide-y divide-line">
            {[
              { n: "1", t: "Sign in", d: "Single local user. Credentials come from your .env." },
              { n: "2", t: "Connect providers", d: "Paste a Vercel, Railway or GitHub token. Test the connection, see its capabilities." },
              { n: "3", t: "Push a bad commit", d: "Or use the Chaos lab to script a failure. Click Investigate and watch the trace." },
            ].map((s) => (
              <div key={s.n} className="flex flex-1 items-start gap-4 p-5">
                <span className="grid size-6 shrink-0 place-items-center rounded-md border border-line bg-raised font-mono text-[11px] text-accent">{s.n}</span>
                <div>
                  <div className="text-[14.5px] font-medium">{s.t}</div>
                  <p className="mt-1 text-[13px] leading-relaxed text-muted">{s.d}</p>
                </div>
              </div>
            ))}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ───────────────────────────── closing CTA + footer

export function Footer() {
  return (
    <footer className="relative overflow-hidden px-4 pt-10">
      <Reveal className="mx-auto max-w-6xl">
        <div className="panel relative overflow-hidden px-6 py-20 text-center sm:py-28">
          <div aria-hidden className="bg-grid absolute inset-0 [mask-image:radial-gradient(60%_70%_at_50%_100%,black,transparent)]" />
          <div
            aria-hidden
            className="absolute bottom-[-14rem] left-1/2 h-[26rem] w-[46rem] -translate-x-1/2 rounded-full blur-3xl"
            style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--accent) 22%, transparent), transparent)" }}
          />
          <div className="relative">
            <h2 className="text-gradient mx-auto max-w-2xl text-balance text-[34px] font-medium leading-[1.08] tracking-[-0.03em] sm:text-[52px]">
              The next red deploy explains itself.
            </h2>
            <p className="mx-auto mt-5 max-w-md text-[15px] leading-relaxed text-muted">Open source, self-hosted, and honest about what it does not know.</p>
            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <ButtonLink href="/console" variant="primary" size="lg" className="group h-11 px-5">
                Open the console <ArrowRight size={15} className="transition-transform group-hover:translate-x-0.5" />
              </ButtonLink>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-11 items-center gap-2 rounded-lg border border-line bg-raised px-5 text-[14px] font-medium transition-colors hover:border-[#3a3a3f]"
              >
                <ProviderIcon provider="github" size={15} /> Star on GitHub
              </a>
            </div>
          </div>
        </div>
      </Reveal>

      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-6 py-10 sm:flex-row sm:items-center">
        <div>
          <Wordmark />
          <p className="mt-2 font-mono text-[11px] text-faint">open source · built in public</p>
        </div>
        <nav className="flex flex-wrap gap-x-6 gap-y-2 text-[13px] text-muted">
          <Link href="/console" className="hover:text-fg">Console</Link>
          <a href={API_DOCS_URL} className="hover:text-fg">API reference</a>
          <a href="#integrations" className="hover:text-fg">Integrations</a>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="hover:text-fg">GitHub</a>
        </nav>
      </div>

      {/* oversized wordmark */}
      <div aria-hidden className="mask-fade-b pointer-events-none mx-auto -mb-[4vw] max-w-6xl select-none text-center text-[21vw] font-semibold leading-[0.8] tracking-[-0.06em] text-raised lg:text-[250px]">
        opscend
      </div>
    </footer>
  );
}
