"use client";

import { AnimatePresence, motion } from "motion/react";
import { Activity } from "lucide-react";
import { useMemo, useState } from "react";
import { TimelineRow, useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { ButtonLink, Dot, Empty, Skeleton } from "@/components/ui/primitives";
import { ProviderIcon, providerName } from "@/components/ui/provider";
import { useApi } from "@/lib/api";
import { cn, dayLabel } from "@/lib/format";
import type { DeployStatus, TimelineItem } from "@/lib/types";

const PROVIDERS = ["vercel", "railway", "github"] as const;
const STATUSES: { id: DeployStatus; color: string }[] = [
  { id: "failed", color: "var(--err)" },
  { id: "building", color: "var(--warn)" },
  { id: "ready", color: "var(--ok)" },
];

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md border px-2.5 font-mono text-[11px] uppercase tracking-wider transition-colors",
        on ? "border-[#3a3a3f] bg-raised text-fg" : "border-line text-muted hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}

export default function TimelinePage() {
  const [provider, setProvider] = useState<string | null>(null);
  const [status, setStatus] = useState<DeployStatus | null>(null);
  const now = useNow();

  const qs = new URLSearchParams({ limit: "150" });
  if (provider) qs.set("provider", provider);
  if (status) qs.set("status", status);
  const { data, error } = useApi<TimelineItem[]>(`/timeline?${qs}`, { refreshInterval: 4000 });

  const groups = useMemo(() => {
    const out: { day: string; items: TimelineItem[] }[] = [];
    for (const item of data ?? []) {
      const day = dayLabel(item.at);
      const last = out[out.length - 1];
      if (last?.day === day) last.items.push(item);
      else out.push({ day, items: [item] });
    }
    return out;
  }, [data]);

  return (
    <>
      <PageHeader
        title="Timeline"
        description="Every deploy, commit and incident across providers, newest first."
        actions={
          <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted">
            <Dot color="var(--ok)" pulse /> live
          </span>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Chip on={!provider} onClick={() => setProvider(null)}>
          All sources
        </Chip>
        {PROVIDERS.map((p) => (
          <Chip key={p} on={provider === p} onClick={() => setProvider(provider === p ? null : p)}>
            <ProviderIcon provider={p} size={11} /> {providerName(p)}
          </Chip>
        ))}
        <span className="mx-1 h-4 w-px bg-line" />
        {STATUSES.map((s) => (
          <Chip key={s.id} on={status === s.id} onClick={() => setStatus(status === s.id ? null : s.id)}>
            <Dot color={s.color} className="scale-75" /> {s.id}
          </Chip>
        ))}
      </div>

      {!data && !error && (
        <div className="space-y-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-[68px] rounded-lg" />
          ))}
        </div>
      )}
      {error && !data && <Empty title="Could not load the timeline">{error.message}</Empty>}
      {data?.length === 0 && (
        <div className="panel">
          <Empty
            icon={<Activity size={18} />}
            title="Nothing on the timeline"
            action={provider || status ? undefined : <ButtonLink href="/console/integrations" variant="primary">Connect a provider</ButtonLink>}
          >
            {provider || status ? "No events match these filters." : "Deploys and commits appear here within a minute of happening."}
          </Empty>
        </div>
      )}

      <div className="space-y-7">
        {groups.map((g) => (
          <section key={g.day}>
            <div className="sticky top-0 z-10 -mx-1 mb-3 flex items-center gap-3 bg-bg/90 px-1 py-1.5 backdrop-blur">
              <span className="label-mono text-fg">{g.day}</span>
              <span className="h-px flex-1 bg-line" />
              <span className="label-mono text-faint">{g.items.length} events</span>
            </div>
            <div className="relative space-y-2.5">
              <span aria-hidden className="absolute bottom-4 left-[13.5px] top-4 w-px bg-line" />
              <AnimatePresence initial={false}>
                {g.items.map((item) => (
                  <motion.div
                    key={`${item.kind}-${item.id}`}
                    layout="position"
                    initial={{ opacity: 0, y: -16, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.35 }}
                  >
                    <TimelineRow item={item} now={now} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
