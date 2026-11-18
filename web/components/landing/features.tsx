"use client";

import { AnimatePresence, motion, useInView } from "motion/react";
import { Activity, Blocks, Check, ShieldAlert, Sparkles, Webhook } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Spotlight } from "@/components/ui/primitives";
import { cn } from "@/lib/format";
import { highlight } from "@/lib/highlight";
import { Reveal, SectionHeading } from "./reveal";

const TABS = [
  {
    id: "timeline",
    label: "Timeline",
    icon: Activity,
    file: "GET /api/timeline",
    lang: "json",
    title: "Every deploy and commit, on one rail",
    body: "Vercel deploys, Railway deploys and GitHub commits merge into a single vertical timeline, colour-coded by provider and status. The failed one is impossible to miss.",
    points: ["Filter by provider, service or status", "Commits sit next to the deploys they caused", "Live: new events appear within seconds"],
    code: `[
  {
    "kind": "deployment",
    "provider": "railway",
    "deployment": {
      "service_name": "storefront-api",
      "status": "failed",
      "commit_sha": "7c3f2de",
      "branch": "main",
      "duration_ms": 48210
    }
  },
  { "kind": "commit", "provider": "github",
    "commit": { "sha": "7c3f2de", "author": "priya",
                "message": "refactor: read stripe secret from env" } },
  { "kind": "deployment", "provider": "vercel",
    "deployment": { "service_name": "storefront-web", "status": "ready" } }
]`,
  },
  {
    id: "ingest",
    label: "Ingest",
    icon: Webhook,
    file: "ingest/webhooks.py",
    lang: "python",
    title: "Webhooks that survive being sent twice",
    body: "Handlers verify the signature, store the raw event under a dedup key and enqueue. Everything else happens in the worker, idempotently. A polling reconciler catches whatever the webhooks missed.",
    points: ["HMAC signature check per provider", "Unique dedup key on every raw event", "Inspect every delivery in the console"],
    code: `@router.post("/webhooks/{provider}", status_code=202)
async def receive(provider: str, request: Request):
    adapter = registry.get(provider)
    body = await request.body()

    # Raises 401 on a bad signature. No work happens here.
    events = adapter.parse_webhook(dict(request.headers), body)

    for event in events:
        stored = await raw_events.insert_once(event)  # dedup_key is unique
        if stored:
            await queue.enqueue("normalize_event", stored.id)

    return {"accepted": len(events)}`,
  },
  {
    id: "adapters",
    label: "Adapters",
    icon: Blocks,
    file: "integrations/base.py",
    lang: "python",
    title: "A provider is one file",
    body: "Each integration implements the same small contract and declares what it can do. The console reads the capability manifest and hides what a provider cannot offer — like runtime logs.",
    points: ["Capability manifest drives the UI", "Register an adapter in one line", "Recorded fixtures, no live calls in tests"],
    code: `class ProviderAdapter(Protocol):
    provider: str
    capabilities: set[Capability]   # LIST_DEPLOYS, BUILD_LOGS, WEBHOOKS ...

    async def validate(self) -> AccountInfo: ...
    async def list_services(self) -> list[ServiceIn]: ...
    async def list_deployments(
        self, service: Service, since: datetime
    ) -> list[DeploymentIn]: ...
    async def get_logs(
        self, deployment: Deployment, kind: LogKind, limit: int = 500
    ) -> list[LogLine]: ...
    def parse_webhook(self, headers: dict, body: bytes) -> list[RawEventIn]: ...`,
  },
  {
    id: "investigator",
    label: "Investigator",
    icon: Sparkles,
    file: "investigation.report",
    lang: "json",
    title: "An answer you can check",
    body: "The investigator calls read-only tools, at most eight times, and must hand back a structured report. Every claim cites a log line, a commit or a deploy that it actually saw — or it says inconclusive.",
    points: ["Evidence ids are validated, not trusted", "Each step is stored as a span", "Runs on Groq with your own key"],
    code: `{
  "likely_cause": "Commit 7c3f2de renamed STRIPE_SECRET to
                   STRIPE_SECRET_KEY; Railway only defines the old name.",
  "confidence": "high",
  "culprit_commit_sha": "7c3f2de",
  "evidence": [
    { "type": "log",    "ref": "log_41",  "quote": "KeyError: 'STRIPE_SECRET_KEY'" },
    { "type": "commit", "ref": "7c3f2de", "quote": "app/config.py +1 -1" },
    { "type": "deploy", "ref": "dpl_a1b9", "quote": "storefront-web ready" }
  ],
  "suggested_fix": "Add STRIPE_SECRET_KEY to the Railway service.",
  "inconclusive": false
}`,
  },
  {
    id: "safety",
    label: "Guardrails",
    icon: ShieldAlert,
    file: "investigator/tools.py",
    lang: "python",
    title: "Read-only by construction",
    body: "The toolset has no write methods at all — there is nothing to jailbreak into. Log text is passed as untrusted data, provider tokens never enter the model context, and they are encrypted at rest.",
    points: ["No rollback, no restart, no write path", "Fernet-encrypted provider tokens", "Step cap and token budget on every run"],
    code: `TOOLS = [
    get_deployment,        # status, commit, timings
    get_logs,              # build or runtime, capped
    list_recent_deploys,   # all providers, last 2 hours
    get_commit_diff,       # files and patches for a sha
    get_health_history,    # uptime checks for a service
]

MAX_TOOL_CALLS = 8
# Log lines are data, never instructions.
UNTRUSTED = "<untrusted_log_data>{text}</untrusted_log_data>"`,
  },
] as const;

const ROTATE_MS = 9000;

export function Features() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-20% 0px" });
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);

  useEffect(() => {
    if (!auto || !inView) return;
    const t = setTimeout(() => setActive((a) => (a + 1) % TABS.length), ROTATE_MS);
    return () => clearTimeout(t);
  }, [active, auto, inView]);

  const tab = TABS[active];
  const html = useMemo(() => highlight(tab.code, tab.lang), [tab]);

  return (
    <section className="relative px-4 py-28">
      <SectionHeading eyebrow="What you get" lead="Timeline. Incidents. Investigator." rest="The data pipeline and the AI that reads it, in one docker compose file." />

      <Reveal delay={0.1} className="mx-auto mt-14 max-w-6xl">
        <div ref={ref} onMouseEnter={() => setAuto(false)}>
          {/* tab bar */}
          <div className="flex gap-2 overflow-x-auto pb-3 [scrollbar-width:none]" role="tablist">
            {TABS.map((t, i) => {
              const on = i === active;
              return (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={on}
                  onClick={() => {
                    setActive(i);
                    setAuto(false);
                  }}
                  className={cn(
                    "relative flex h-11 min-w-[140px] flex-1 items-center gap-2.5 overflow-hidden rounded-xl border px-4 font-mono text-[11px] uppercase tracking-[0.1em] transition-colors",
                    on ? "border-[#34343a] bg-raised text-fg" : "border-line bg-surface text-muted hover:text-fg",
                  )}
                >
                  <t.icon size={14} className={on ? "text-accent" : ""} />
                  {t.label}
                  {on && auto && inView && (
                    <motion.span
                      key={`p-${active}`}
                      className="absolute inset-x-0 bottom-0 h-px origin-left bg-accent"
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: ROTATE_MS / 1000, ease: "linear" }}
                    />
                  )}
                  {on && !auto && <motion.span layoutId="tab-line" className="absolute inset-x-0 bottom-0 h-px bg-accent" />}
                </button>
              );
            })}
          </div>

          {/* panel */}
          <Spotlight className="panel grid overflow-hidden lg:grid-cols-[1.25fr_1fr]">
            <div className="relative min-h-[380px] border-b border-line lg:border-b-0 lg:border-r">
              <div className="flex h-10 items-center gap-2 border-b border-line px-4 font-mono text-[11px] text-muted">
                <span className="size-2 rounded-full bg-accent/80" />
                {tab.file}
              </div>
              <AnimatePresence mode="wait">
                <motion.pre
                  key={tab.id}
                  initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: -6, filter: "blur(4px)" }}
                  transition={{ duration: 0.28 }}
                  className="code overflow-x-auto p-5 text-fg/85"
                >
                  <code dangerouslySetInnerHTML={{ __html: html }} />
                </motion.pre>
              </AnimatePresence>
            </div>
            <div className="flex flex-col justify-center p-7 sm:p-10">
              <AnimatePresence mode="wait">
                <motion.div
                  key={tab.id}
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.28 }}
                >
                  <div className="mb-5 grid size-10 place-items-center rounded-lg border border-line bg-raised text-accent">
                    <tab.icon size={18} />
                  </div>
                  <h3 className="text-[22px] font-medium leading-tight tracking-tight">{tab.title}</h3>
                  <p className="mt-3 text-[14.5px] leading-relaxed text-muted">{tab.body}</p>
                  <ul className="mt-6 space-y-2.5">
                    {tab.points.map((p) => (
                      <li key={p} className="flex items-start gap-2.5 text-[13.5px] text-fg/90">
                        <Check size={14} className="mt-0.5 shrink-0 text-accent" />
                        {p}
                      </li>
                    ))}
                  </ul>
                </motion.div>
              </AnimatePresence>
            </div>
          </Spotlight>
        </div>
      </Reveal>
    </section>
  );
}
