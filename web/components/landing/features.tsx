"use client";

import { AnimatePresence, motion, useInView } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/format";
import { highlight } from "@/lib/highlight";
import { Rise, Section, SmoothHeight } from "./reveal";

const TABS = [
  {
    id: "timeline",
    label: "Timeline",
    file: "GET /api/timeline",
    lang: "json",
    title: "Every deploy and commit, on one rail",
    body: "Deploys and commits from every provider, merged and colour-coded.",
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
    file: "ingest/webhooks.py",
    lang: "python",
    title: "Webhooks that survive being sent twice",
    body: "Verify, store under a dedup key, enqueue. A poller catches what webhooks miss.",
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
    file: "integrations/base.py",
    lang: "python",
    title: "A provider is one file",
    body: "One small contract per provider, plus a list of what it can do.",
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
    file: "investigation.report",
    lang: "json",
    title: "An answer you can check",
    body: "At most eight read-only tool calls, then a report that cites what it saw.",
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
    file: "investigator/tools.py",
    lang: "python",
    title: "Read-only by construction",
    body: "No write tools exist. Logs are treated as data, tokens never reach the model.",
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
    <Section
      no="02"
      label="What you get"
      title={["The pipeline,", "and the thing", "that reads it."]}
      
    >
      <Rise>
        <div ref={ref} onMouseEnter={() => setAuto(false)} className="grid grid-cols-1 border border-line lg:grid-cols-[260px_1fr]">
          {/* index */}
          <div role="tablist" aria-orientation="vertical" className="flex overflow-x-auto border-b border-line lg:block lg:border-b-0 lg:border-r">
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
                    "mono relative flex h-12 shrink-0 items-center gap-4 border-r border-line px-5 text-left text-[12px] uppercase tracking-[0.12em] transition-colors duration-300 lg:h-14 lg:w-full lg:border-b lg:border-r-0",
                    on ? "text-bg" : "text-muted hover:bg-raised hover:text-fg",
                  )}
                >
                  {on && <motion.span layoutId="feature-active" className="absolute inset-0 bg-fg" transition={{ duration: 0.45, ease: [0.2, 0.7, 0.2, 1] }} />}
                  <span className={cn("relative transition-colors duration-300", on ? "opacity-60" : "text-faint")}>{String(i + 1).padStart(2, "0")}</span>
                  <span className="relative">{t.label}</span>
                  {on && auto && inView && (
                    <motion.span
                      key={`p-${active}`}
                      className="absolute inset-x-0 bottom-0 h-[3px] origin-left bg-[var(--signal)]"
                      initial={{ scaleX: 0 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: ROTATE_MS / 1000, ease: "linear" }}
                    />
                  )}
                </button>
              );
            })}
          </div>

          {/* sheet */}
          <div className="grid min-w-0 grid-cols-1 xl:grid-cols-[1.25fr_1fr]">
            <div className="min-h-[400px] min-w-0 border-b border-line bg-surface xl:border-b-0 xl:border-r">
              <div className="label flex h-10 items-center justify-between border-b border-line px-5 normal-case tracking-normal">
                <span>{tab.file}</span>
                <span className="uppercase tracking-[0.12em] text-faint">{tab.lang}</span>
              </div>
              <SmoothHeight>
              <AnimatePresence mode="wait">
                <motion.pre
                  key={tab.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3, ease: "easeInOut" }}
                  className="code overflow-x-auto p-5 text-fg/85"
                >
                  <code dangerouslySetInnerHTML={{ __html: html }} />
                </motion.pre>
              </AnimatePresence>
              </SmoothHeight>
            </div>
            <SmoothHeight>
            <div className="p-6 sm:p-8">
              <AnimatePresence mode="wait">
                <motion.div key={tab.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.32, ease: [0.2, 0.7, 0.2, 1] }}>
                  <h3 className="display text-[38px] sm:text-[44px]">{tab.title}</h3>
                  <p className="mt-5 text-[14.5px] leading-relaxed text-muted">{tab.body}</p>
                </motion.div>
              </AnimatePresence>
            </div>
            </SmoothHeight>
          </div>
        </div>
      </Rise>
    </Section>
  );
}
