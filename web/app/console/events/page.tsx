"use client";

import { AnimatePresence, motion } from "motion/react";
import { ChevronRight, Webhook } from "lucide-react";
import { useState } from "react";
import { useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { CopyButton, Dot, Empty, Mono, Panel, PanelHeader, Skeleton, Tag } from "@/components/ui/primitives";
import { ProviderIcon } from "@/components/ui/provider";
import { useApi } from "@/lib/api";
import { clock, cn, timeAgo } from "@/lib/format";
import { highlight } from "@/lib/highlight";
import type { RawEvent } from "@/lib/types";

const SOURCE_COLOR = { webhook: "var(--info)", poll: "var(--muted)", demo: "var(--warn)" } as const;

export default function EventsPage() {
  const { data, error } = useApi<RawEvent[]>("/events?limit=100", { refreshInterval: 3000 });
  const [open, setOpen] = useState<string | null>(null);
  const now = useNow();
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";
  const curl = `curl -i -X POST ${origin}/api/webhooks/github \\\n  -H "X-GitHub-Event: push" \\\n  -H "X-Hub-Signature-256: sha256=<hmac of body with your webhook secret>" \\\n  -d @push.json`;

  return (
    <>
      <PageHeader
        title="Event inspector"
        description="Every webhook delivery and poll result, stored raw before it is normalized. Duplicates are kept visible and never processed twice."
        actions={
          <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted">
            <Dot color="var(--ok)" pulse /> tailing
          </span>
        }
      />

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel>
          <div className="grid grid-cols-[16px_70px_minmax(0,1fr)_auto] gap-3 border-b border-line px-4 py-2 font-mono text-[10.5px] uppercase tracking-wider text-faint sm:grid-cols-[16px_70px_90px_minmax(0,1fr)_minmax(0,1.2fr)_auto]">
            <span />
            <span>Received</span>
            <span className="hidden sm:block">Source</span>
            <span>Event</span>
            <span className="hidden sm:block">Dedup key</span>
            <span>State</span>
          </div>
          {!data && !error && <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-7" />)}</div>}
          {error && !data && <Empty title="Could not load events">{error.message}</Empty>}
          {data?.length === 0 && (
            <Empty icon={<Webhook size={18} />} title="No events received yet">
              Point a provider webhook at this instance, or wait for the first poll.
            </Empty>
          )}
          {data?.map((e) => {
            const isOpen = open === e.id;
            const lag = e.processed_at ? new Date(e.processed_at).getTime() - new Date(e.received_at).getTime() : null;
            return (
              <div key={e.id} className={cn("border-b border-line-soft last:border-0", e.duplicate && "opacity-55")}>
                <button
                  onClick={() => setOpen(isOpen ? null : e.id)}
                  aria-expanded={isOpen}
                  className="grid w-full grid-cols-[16px_70px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2 text-left font-mono text-[11.5px] transition-colors hover:bg-raised/50 sm:grid-cols-[16px_70px_90px_minmax(0,1fr)_minmax(0,1.2fr)_auto]"
                >
                  <ChevronRight size={11} className={cn("text-faint transition-transform", isOpen && "rotate-90")} />
                  <span className="text-muted" title={timeAgo(e.received_at, now)}>
                    {clock(e.received_at)}
                  </span>
                  <span className="hidden items-center gap-1.5 sm:flex" style={{ color: SOURCE_COLOR[e.source] }}>
                    {e.source}
                  </span>
                  <span className="flex min-w-0 items-center gap-2">
                    <ProviderIcon provider={e.provider} size={11} className="shrink-0" />
                    <span className="truncate text-fg">{e.event_type}</span>
                  </span>
                  <span className="hidden truncate text-faint sm:block">{e.dedup_key}</span>
                  <span>
                    {e.duplicate ? <Tag color="var(--warn)">duplicate</Tag> : e.processed_at ? <Tag color="var(--ok)">{lag != null && lag >= 0 ? `${lag}ms` : "done"}</Tag> : <Tag>pending</Tag>}
                  </span>
                </button>
                <AnimatePresence>
                  {isOpen && (
                    <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
                      <div className="mx-4 mb-3 rounded-lg border border-line bg-bg/60">
                        <div className="flex items-center gap-4 border-b border-line px-3 py-1.5 font-mono text-[11px] text-muted">
                          <span>id <Mono value={e.id} className="text-[11px]" /></span>
                          <span className="min-w-0 truncate">dedup <Mono value={e.dedup_key} className="text-[11px]" /></span>
                          <CopyButton value={JSON.stringify(e.payload, null, 2)} className="ml-auto" label="Copy payload" />
                        </div>
                        <pre className="code max-h-80 overflow-auto p-3 text-[11.5px] text-fg/80">
                          <code dangerouslySetInnerHTML={{ __html: highlight(JSON.stringify(e.payload, null, 2), "json") }} />
                        </pre>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Webhook endpoints" />
            <div className="divide-y divide-line-soft">
              {["vercel", "railway", "github"].map((p) => (
                <div key={p} className="flex items-center gap-2.5 px-4 py-2.5">
                  <ProviderIcon provider={p} size={12} />
                  <code className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-muted">
                    <span className="text-accent">POST</span> /api/webhooks/{p}
                  </code>
                  <CopyButton value={`${origin}/api/webhooks/${p}`} />
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <PanelHeader title="Replay a delivery" right={<CopyButton value={curl} />} />
            <pre className="code overflow-x-auto p-4 text-[11.5px] text-fg/80">
              <code dangerouslySetInnerHTML={{ __html: highlight(curl, "bash") }} />
            </pre>
            <p className="border-t border-line px-4 py-3 text-[12.5px] leading-relaxed text-muted">
              Send it twice. The second delivery shows up as <span className="text-warn">duplicate</span> and creates nothing.
            </p>
          </Panel>
        </div>
      </div>
    </>
  );
}
