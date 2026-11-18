"use client";

import { GitBranch, GitCommitHorizontal, Siren, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Dot, Mono, statusColor, StatusBadge, Tag } from "@/components/ui/primitives";
import { ProviderIcon, providerColor } from "@/components/ui/provider";
import { api, ApiError } from "@/lib/api";
import { clock, duration, firstLine, shortSha, timeAgo } from "@/lib/format";
import type { Commit, Deployment, Incident, Investigation, TimelineItem } from "@/lib/types";
import { useToast } from "./toast";

/** Re-render on an interval so "3m ago" labels stay honest. */
export function useNow(ms = 15000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Starts an investigation and jumps to its live trace. */
export function useInvestigate() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async (target: { deploymentId?: string; incidentId?: string }) => {
    setBusy(true);
    try {
      const path = target.deploymentId ? `/deployments/${target.deploymentId}/investigate` : `/incidents/${target.incidentId}/investigate`;
      const inv = await api<Investigation>(path, { method: "POST" });
      router.push(`/console/investigations/${inv.id}`);
    } catch (e) {
      const err = e as ApiError;
      toast.error(err.status === 409 ? "Investigator is not configured" : "Could not start the investigation", err.message);
      setBusy(false);
    }
  };
  return { run, busy };
}

export function InvestigateButton({ deploymentId, incidentId, size = "sm", label = "Investigate" }: { deploymentId?: string; incidentId?: string; size?: "sm" | "md"; label?: string }) {
  const { run, busy } = useInvestigate();
  return (
    <Button
      variant="primary"
      size={size}
      loading={busy}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        run({ deploymentId, incidentId });
      }}
    >
      {!busy && <Sparkles size={12} />} {label}
    </Button>
  );
}

/** Compact table row for a deployment. */
export function DeployRow({ d, now }: { d: Deployment; now: number }) {
  return (
    <Link
      href={`/console/deployments/${d.id}`}
      className="group grid grid-cols-[auto_minmax(0,1.1fr)_minmax(0,2fr)_auto] items-center gap-3 border-b border-line-soft px-4 py-2.5 text-[13px] transition-colors last:border-0 hover:bg-raised/50 sm:grid-cols-[auto_minmax(0,1.1fr)_minmax(0,2fr)_90px_70px_70px]"
    >
      <span className="h-6 w-0.5 rounded-full" style={{ background: statusColor(d.status) }} />
      <span className="flex min-w-0 items-center gap-2">
        <ProviderIcon provider={d.provider} size={13} className="shrink-0" />
        <span className="truncate font-medium">{d.service_name}</span>
      </span>
      <span className="flex min-w-0 items-center gap-2 text-muted">
        <span className="shrink-0 font-mono text-[11.5px] text-fg/80">{shortSha(d.commit_sha)}</span>
        <span className="truncate">{firstLine(d.commit_message) || "—"}</span>
      </span>
      <span>
        <StatusBadge status={d.status} />
      </span>
      <span className="hidden text-right font-mono text-[11.5px] text-muted sm:block">{duration(d.duration_ms)}</span>
      <span className="hidden text-right font-mono text-[11.5px] text-faint sm:block" title={new Date(d.started_at).toLocaleString()}>
        {timeAgo(d.started_at, now)}
      </span>
    </Link>
  );
}

// ───────────────────────────── timeline items

function Rail({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span className="relative z-[1] grid size-7 shrink-0 place-items-center rounded-md border bg-raised" style={{ borderColor: `color-mix(in oklab, ${color} 35%, var(--line))` }}>
      {children}
    </span>
  );
}

function DeploymentCard({ d, now }: { d: Deployment; now: number }) {
  const failed = d.status === "failed";
  return (
    <Link
      href={`/console/deployments/${d.id}`}
      className="block min-w-0 flex-1 rounded-lg border bg-surface px-3.5 py-3 transition-colors hover:bg-raised/60"
      style={{ borderColor: failed ? "color-mix(in oklab, var(--err) 40%, var(--line))" : "var(--line)" }}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-[13.5px] font-medium">{d.service_name}</span>
        <StatusBadge status={d.status} />
        {d.environment && <span className="font-mono text-[11px] text-faint">{d.environment}</span>}
        <span className="ml-auto flex items-center gap-3 font-mono text-[11px] text-muted">
          <span>{duration(d.duration_ms)}</span>
          <span className="text-faint" title={new Date(d.started_at).toLocaleString()}>
            {clock(d.started_at)} · {timeAgo(d.started_at, now)}
          </span>
        </span>
      </div>
      <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted">
        <span className="flex items-center gap-1 font-mono text-[11.5px]">
          <GitCommitHorizontal size={12} /> {shortSha(d.commit_sha)}
        </span>
        {d.branch && (
          <span className="flex items-center gap-1 font-mono text-[11.5px]">
            <GitBranch size={11} /> {d.branch}
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{firstLine(d.commit_message)}</span>
        {failed && <InvestigateButton deploymentId={d.id} />}
      </div>
    </Link>
  );
}

function CommitCard({ c, now }: { c: Commit; now: number }) {
  return (
    <div className="min-w-0 flex-1 rounded-lg border border-dashed border-line px-3.5 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]">
        <Mono value={c.sha} display={shortSha(c.sha)} className="text-fg/80" />
        <span className="min-w-0 flex-1 truncate text-fg/90">{firstLine(c.message)}</span>
        <span className="font-mono text-[11px] text-muted">{c.author}</span>
        <span className="font-mono text-[11px] text-faint">
          {c.repo} · {timeAgo(c.committed_at, now)}
        </span>
      </div>
    </div>
  );
}

function IncidentCard({ i, now }: { i: Incident; now: number }) {
  const open = i.status === "open";
  return (
    <Link
      href={i.deployment_id ? `/console/deployments/${i.deployment_id}` : "/console/incidents"}
      className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3.5 py-2.5 text-[12.5px] transition-colors hover:bg-raised/60"
      style={{ borderColor: open ? "color-mix(in oklab, var(--err) 40%, var(--line))" : "var(--line)", background: open ? "color-mix(in oklab, var(--err) 5%, var(--surface))" : "var(--surface)" }}
    >
      <Tag color={open ? "var(--err)" : "var(--muted)"}>{open ? "incident opened" : "incident resolved"}</Tag>
      <span className="min-w-0 flex-1 truncate">{i.title}</span>
      <span className="font-mono text-[11px] text-faint">{timeAgo(i.opened_at, now)}</span>
    </Link>
  );
}

export function TimelineRow({ item, now }: { item: TimelineItem; now: number }) {
  if (item.kind === "deployment") {
    return (
      <div className="relative flex gap-3">
        <Rail color={providerColor(item.provider)}>
          <ProviderIcon provider={item.provider} size={13} />
          {item.deployment.status === "building" && <Dot color="var(--warn)" pulse className="absolute -right-0.5 -top-0.5 scale-75" />}
        </Rail>
        <DeploymentCard d={item.deployment} now={now} />
      </div>
    );
  }
  if (item.kind === "commit") {
    return (
      <div className="relative flex gap-3">
        <Rail color={providerColor("github")}>
          <ProviderIcon provider="github" size={13} />
        </Rail>
        <CommitCard c={item.commit} now={now} />
      </div>
    );
  }
  return (
    <div className="relative flex gap-3">
      <Rail color="var(--err)">
        <Siren size={13} className={item.incident.status === "open" ? "text-err" : "text-muted"} />
      </Rail>
      <IncidentCard i={item.incident} now={now} />
    </div>
  );
}
