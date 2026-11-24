"use client";

import { CircleCheck, HeartPulse, Rocket } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";
import { InvestigateButton, useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { useToast } from "@/components/console/toast";
import { Button, ButtonLink, Empty, Panel, Skeleton, Tag } from "@/components/ui/primitives";
import { ProviderIcon } from "@/components/ui/provider";
import { api, ApiError, useApi } from "@/lib/api";
import { cn, timeAgo } from "@/lib/format";
import type { Incident } from "@/lib/types";

export default function IncidentsPage() {
  const [filter, setFilter] = useState<"open" | "resolved" | "all">("open");
  const path = `/incidents${filter === "all" ? "" : `?status=${filter}`}`;
  const { data, error, mutate: refresh } = useApi<Incident[]>(path, { refreshInterval: 5000 });
  const toast = useToast();
  const now = useNow();
  const [busy, setBusy] = useState<string | null>(null);

  const resolve = async (id: string) => {
    setBusy(id);
    try {
      await api(`/incidents/${id}/resolve`, { method: "POST" });
      toast.ok("Incident resolved");
      await Promise.all([refresh(), mutate("/incidents?status=open"), mutate("/overview")]);
    } catch (e) {
      toast.error("Could not resolve the incident", (e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Incidents"
        description="Opened automatically when a deploy fails or a service fails two health checks. One open incident per service."
        actions={
          <div className="flex rounded-lg border border-line p-0.5">
            {(["open", "resolved", "all"] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={cn("h-7 rounded-md px-3 font-mono text-[11px] uppercase tracking-wider", filter === f ? "bg-raised text-fg" : "text-muted hover:text-fg")}>
                {f}
              </button>
            ))}
          </div>
        }
      />
      <Panel>
        {!data && !error && <div className="space-y-2 p-4">{[0, 1].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {error && !data && <Empty title="Could not load incidents">{error.message}</Empty>}
        {data?.length === 0 && (
          <Empty icon={<CircleCheck size={18} className="text-ok" />} title={filter === "open" ? "No open incidents" : "No incidents"}>
            {filter === "open" ? "Every service's latest deploy is healthy." : "Nothing has failed yet."}
          </Empty>
        )}
        {data?.map((i, n) => {
          const open = i.status === "open";
          return (
            <div key={i.id} data-tour={n === 0 ? "incident" : undefined} className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-4 py-3.5 last:border-0">
              <span className={cn("grid size-8 shrink-0 place-items-center rounded-md border", open ? "border-err/40 bg-err/10 text-err" : "border-line bg-raised text-muted")}>
                {i.trigger === "deploy_failed" ? <Rocket size={14} /> : <HeartPulse size={14} />}
              </span>
              <div className="min-w-0 flex-1 basis-[200px]">
                <div className="flex items-center gap-2 text-[13.5px]">
                  <span className="truncate font-medium">{i.title}</span>
                  <Tag color={open ? "var(--err)" : "var(--muted)"}>{i.status}</Tag>
                  {i.times_seen > 1 && (
                    <span title="Incidents with the same error in the last 180 days">
                      <Tag color="var(--warn)">seen {i.times_seen}×</Tag>
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[11px] text-muted">
                  <ProviderIcon provider={i.provider} size={11} className="shrink-0" /> {i.service_name}
                  <span className="text-faint">· {i.trigger.replace(/_/g, " ")} · opened {timeAgo(i.opened_at, now)}</span>
                  {i.resolved_at && <span className="text-faint">· resolved {timeAgo(i.resolved_at, now)}</span>}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2 max-sm:w-full max-sm:pl-12">
                {i.deployment_id && (
                  <Link href={`/console/deployments/${i.deployment_id}`} className="font-mono text-[11px] text-muted hover:text-fg">
                    deploy →
                  </Link>
                )}
                {i.investigation_id ? (
                  <ButtonLink size="sm" href={`/console/investigations/${i.investigation_id}`}>Report</ButtonLink>
                ) : (
                  open && <InvestigateButton incidentId={i.id} />
                )}
                {open && (
                  <Button size="sm" loading={busy === i.id} onClick={() => resolve(i.id)}>
                    Resolve
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </Panel>
    </>
  );
}
