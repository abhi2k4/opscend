"use client";

import { ArrowLeft, Rocket } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { InvestigateButton } from "@/components/console/deploys";
import { ReportView, RunMeta, TraceView } from "@/components/console/investigation";
import { ButtonLink, Dot, Empty, Mono, Panel, PanelHeader, Skeleton, Tag } from "@/components/ui/primitives";
import { useApi } from "@/lib/api";
import type { Investigation } from "@/lib/types";

const STATUS_COLOR = { queued: "var(--muted)", running: "var(--accent)", completed: "var(--ok)", failed: "var(--err)" } as const;

export default function InvestigationPage() {
  const { id } = useParams<{ id: string }>();
  // Poll every second while the run is live; stop once it settles.
  const { data: inv, error } = useApi<Investigation>(`/investigations/${id}`, {
    refreshInterval: (cur) => (!cur || cur.status === "running" || cur.status === "queued" ? 1000 : 0),
  });

  if (error && !inv) return <Empty title={error.status === 404 ? "Investigation not found" : "Could not load this investigation"}>{error.message}</Empty>;
  if (!inv) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-14 rounded-xl" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Skeleton className="h-96 rounded-xl" />
          <Skeleton className="h-96 rounded-xl" />
        </div>
      </div>
    );
  }

  const live = inv.status === "running" || inv.status === "queued";
  return (
    <>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Link href="/console/investigations" className="mb-2 inline-flex items-center gap-1.5 font-mono text-[11px] text-muted hover:text-fg">
            <ArrowLeft size={11} /> all investigations
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[20px] font-medium tracking-tight">{inv.service_name ?? "Investigation"}</h1>
            <Tag color={STATUS_COLOR[inv.status]}>
              <Dot color={STATUS_COLOR[inv.status]} pulse={live} className="scale-75" /> {inv.status}
            </Tag>
            {inv.model === "simulated" && (
              <span title="The steps and the conclusion come from the demo's script, not from a model. The tools and the evidence check are real.">
                <Tag color="var(--warn)">simulated run</Tag>
              </span>
            )}
            <Mono value={inv.id} display={inv.id.length > 14 ? `${inv.id.slice(0, 12)}…` : inv.id} />
          </div>
          <div className="mt-2">
            <RunMeta inv={inv} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {inv.deployment_id && (
            <ButtonLink href={`/console/deployments/${inv.deployment_id}`}>
              <Rocket size={13} /> Deploy & logs
            </ButtonLink>
          )}
          {!live && inv.deployment_id && <InvestigateButton deploymentId={inv.deployment_id} size="md" label="Re-run" />}
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
        <Panel data-tour="trace">
          <PanelHeader title="Trace" right={<span className="label-mono text-faint">click a span for input and output</span>} />
          <TraceView inv={inv} />
        </Panel>
        <Panel data-tour="report" className="lg:sticky lg:top-0">
          <PanelHeader title="Report" right={<span className="label-mono text-faint">read-only analysis</span>} />
          <ReportView inv={inv} />
        </Panel>
      </div>
    </>
  );
}
