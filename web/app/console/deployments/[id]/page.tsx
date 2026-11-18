"use client";

import { ExternalLink, FileDiff, GitBranch, ScrollText, Sparkles, Terminal } from "lucide-react";
import { motion } from "motion/react";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { InvestigateButton, useNow } from "@/components/console/deploys";
import { DiffView, LogViewer } from "@/components/console/logs";
import { ButtonLink, Empty, HealthBadge, Mono, Panel, Skeleton, StatusBadge, Tag } from "@/components/ui/primitives";
import { ProviderTile, providerName } from "@/components/ui/provider";
import { useApi } from "@/lib/api";
import { cn, duration, firstLine, shortSha, timeAgo } from "@/lib/format";
import type { DeploymentDetail, LogLine } from "@/lib/types";

type Tab = "build" | "runtime" | "diff";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 bg-surface px-4 py-3">
      <div className="label-mono mb-1">{label}</div>
      <div className="truncate text-[13px]">{children}</div>
    </div>
  );
}

function DeployDetail() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const focusLog = params.get("log");
  const now = useNow();
  const { data: d, error } = useApi<DeploymentDetail>(`/deployments/${id}`, { refreshInterval: (cur) => (cur?.status === "building" || cur?.status === "queued" ? 3000 : 0) });
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) ?? "build");

  // An evidence link carries only a log id; open whichever log stream holds it.
  const build = useApi<LogLine[]>(focusLog ? `/deployments/${id}/logs?kind=build` : null);
  const runtime = useApi<LogLine[]>(focusLog ? `/deployments/${id}/logs?kind=runtime` : null);
  useEffect(() => {
    if (!focusLog) return;
    if (runtime.data?.some((l) => l.id === focusLog)) setTab("runtime");
    else if (build.data?.some((l) => l.id === focusLog)) setTab("build");
  }, [focusLog, build.data, runtime.data]);

  if (error && !d) return <Empty title={error.status === 404 ? "Deploy not found" : "Could not load this deploy"}>{error.message}</Empty>;
  if (!d) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16 rounded-xl" />
        <Skeleton className="h-[70px] rounded-xl" />
        <Skeleton className="h-96 rounded-xl" />
      </div>
    );
  }

  const tabs: { id: Tab; label: string; icon: typeof Terminal; show: boolean }[] = [
    { id: "build", label: "Build logs", icon: Terminal, show: d.capabilities.includes("BUILD_LOGS") },
    { id: "runtime", label: "Runtime logs", icon: ScrollText, show: d.capabilities.includes("RUNTIME_LOGS") },
    { id: "diff", label: "Commit diff", icon: FileDiff, show: !!d.commit_sha },
  ];
  const visible = tabs.filter((t) => t.show);
  const current = visible.find((t) => t.id === tab) ?? visible[0];
  const failed = d.status === "failed";

  return (
    <>
      <div className="mb-5 flex flex-wrap items-start gap-4">
        <ProviderTile provider={d.provider} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[20px] font-medium tracking-tight">{d.service_name}</h1>
            <StatusBadge status={d.status} />
            {d.incident_id && <Tag color="var(--err)">incident</Tag>}
          </div>
          <p className="mt-1 truncate text-[13px] text-muted">{firstLine(d.commit_message) || "No commit message"}</p>
        </div>
        <div className="flex items-center gap-2">
          {d.url && (
            <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[13px] hover:border-[#3a3a3f]">
              {providerName(d.provider)} <ExternalLink size={12} />
            </a>
          )}
          {d.investigation_id && (
            <ButtonLink href={`/console/investigations/${d.investigation_id}`} variant={failed ? "primary" : "secondary"}>
              <Sparkles size={13} /> View investigation
            </ButtonLink>
          )}
          {(failed || !d.investigation_id) && <InvestigateButton deploymentId={d.id} size="md" label={d.investigation_id ? "Re-run" : "Investigate"} />}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <Field label="Commit">{d.commit_sha ? <Mono value={d.commit_sha} display={shortSha(d.commit_sha)} className="text-fg" /> : "—"}</Field>
        <Field label="Branch">
          <span className="inline-flex items-center gap-1.5 font-mono text-[12px]">
            <GitBranch size={12} className="text-faint" /> {d.branch ?? "—"}
          </span>
        </Field>
        <Field label="Author">{d.commit_author ?? "—"}</Field>
        <Field label="Duration">
          <span className="font-mono text-[12px]">{duration(d.duration_ms)}</span>
        </Field>
        <Field label="Started">
          <span title={new Date(d.started_at).toLocaleString()}>{timeAgo(d.started_at, now)}</span>
        </Field>
        <Field label="Service health">
          <HealthBadge health={d.service.health} />
        </Field>
      </div>

      <Panel className="mt-4">
        <div className="flex items-center gap-1 border-b border-line px-2" role="tablist">
          {visible.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={current?.id === t.id}
              onClick={() => setTab(t.id)}
              className={cn("relative flex h-10 items-center gap-2 px-3 font-mono text-[11px] uppercase tracking-wider transition-colors", current?.id === t.id ? "text-fg" : "text-muted hover:text-fg")}
            >
              <t.icon size={13} /> {t.label}
              {current?.id === t.id && <motion.span layoutId="deploy-tab" className="absolute inset-x-2 bottom-0 h-px bg-accent" />}
            </button>
          ))}
          <span className="ml-auto pr-2 font-mono text-[11px] text-faint">
            <Mono value={d.id} display={`id ${d.id.length > 14 ? `${d.id.slice(0, 12)}…` : d.id}`} />
          </span>
        </div>
        {!current && <Empty title="This provider exposes no logs">Its capability manifest lists neither build nor runtime logs.</Empty>}
        {current?.id === "build" && <LogViewer deploymentId={d.id} kind="build" focusId={focusLog} />}
        {current?.id === "runtime" && <LogViewer deploymentId={d.id} kind="runtime" focusId={focusLog} />}
        {current?.id === "diff" && <DiffView deploymentId={d.id} />}
      </Panel>
    </>
  );
}

export default function DeployPage() {
  return (
    <Suspense>
      <DeployDetail />
    </Suspense>
  );
}
