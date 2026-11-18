"use client";

import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { ArrowRight, CircleCheck, Siren } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { DeployRow, InvestigateButton, useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { ButtonLink, Empty, HealthBadge, Panel, PanelHeader, Skeleton, StatusBadge, Tag } from "@/components/ui/primitives";
import { ProviderTile } from "@/components/ui/provider";
import { useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Overview, Service } from "@/lib/types";

function Count({ value }: { value: number }) {
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => Math.round(v).toString());
  useEffect(() => {
    const c = animate(mv, value, { duration: 0.7, ease: "easeOut" });
    return c.stop;
  }, [mv, value]);
  return <motion.span>{text}</motion.span>;
}

function Stat({ label, value, tone, hint }: { label: string; value: number; tone?: string; hint?: string }) {
  return (
    <div className="bg-surface p-4">
      <div className="label-mono">{label}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-[26px] font-medium leading-none tracking-tight tabular-nums" style={{ color: tone && value > 0 ? tone : undefined }}>
          <Count value={value} />
        </span>
        {hint && <span className="font-mono text-[11px] text-faint">{hint}</span>}
      </div>
    </div>
  );
}

function ServiceCard({ s, now }: { s: Service; now: number }) {
  const max = Math.max(1, ...s.health_history.map((h) => h.latency_ms ?? 0));
  return (
    <div className="panel p-4">
      <div className="flex items-start gap-3">
        <ProviderTile provider={s.provider} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-medium">{s.name}</div>
          <div className="truncate font-mono text-[11px] text-faint">{s.repo ?? s.external_id}</div>
        </div>
        <HealthBadge health={s.health} />
      </div>
      {/* uptime bars: height is latency, colour is pass/fail */}
      <div className="mt-4 flex h-8 items-end gap-[3px]" aria-label="Recent health checks">
        {s.health_history.length === 0 && <span className="self-center font-mono text-[11px] text-faint">no health URL configured</span>}
        {s.health_history.map((h, i) => (
          <span
            key={i}
            title={`${new Date(h.checked_at).toLocaleTimeString()} · ${h.status_code ?? "no response"} · ${h.latency_ms ?? "—"}ms`}
            className="flex-1 rounded-[1px] transition-opacity hover:opacity-60"
            style={{ height: `${h.ok ? 25 + ((h.latency_ms ?? 0) / max) * 75 : 100}%`, background: h.ok ? "color-mix(in oklab, var(--ok) 65%, transparent)" : "var(--err)" }}
          />
        ))}
      </div>
      <div className="mt-3 flex items-center justify-between font-mono text-[11px] text-muted">
        <span>{s.latency_ms != null ? `${s.latency_ms}ms` : "—"}</span>
        <span className="flex items-center gap-2">
          {s.last_deploy_status && <StatusBadge status={s.last_deploy_status} />}
          <span className="text-faint">{timeAgo(s.last_deploy_at, now)}</span>
        </span>
      </div>
    </div>
  );
}

function ActivityChart({ activity }: { activity: Overview["activity"] }) {
  const max = Math.max(1, ...activity.map((a) => a.ready + a.failed));
  return (
    <div className="flex h-24 items-end gap-1 px-4 pb-3 pt-4">
      {activity.map((a) => {
        const total = a.ready + a.failed;
        return (
          <div key={a.hour} className="group relative flex h-full flex-1 flex-col justify-end" title={`${new Date(a.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${a.ready} ready · ${a.failed} failed`}>
            {total === 0 ? (
              <span className="h-px bg-line" />
            ) : (
              <>
                {a.failed > 0 && <motion.span initial={{ height: 0 }} animate={{ height: `${(a.failed / max) * 100}%` }} className="rounded-t-[2px] bg-err" />}
                {a.ready > 0 && (
                  <motion.span
                    initial={{ height: 0 }}
                    animate={{ height: `${(a.ready / max) * 100}%` }}
                    className={`bg-ok/60 group-hover:bg-ok ${a.failed ? "" : "rounded-t-[2px]"}`}
                  />
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function OverviewPage() {
  const { data, error } = useApi<Overview>("/overview", { refreshInterval: 5000 });
  const now = useNow();

  if (!data) {
    return (
      <>
        <PageHeader title="Overview" />
        {error ? <Empty title="Could not load the overview">{error.message}</Empty> : <LoadingState />}
      </>
    );
  }

  const { stats } = data;
  return (
    <>
      <PageHeader
        title="Overview"
        description={stats.open_incidents > 0 ? `${stats.open_incidents} open ${stats.open_incidents > 1 ? "incidents need" : "incident needs"} attention.` : "All services are deploying cleanly."}
        actions={
          <ButtonLink href="/console/timeline">
            Timeline <ArrowRight size={13} />
          </ButtonLink>
        }
      />

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Services" value={stats.services} />
        <Stat label="Down" value={stats.services_down} tone="var(--err)" />
        <Stat label="Deploys" value={stats.deploys_24h} hint="24h" />
        <Stat label="Failed" value={stats.failed_24h} tone="var(--err)" hint="24h" />
        <Stat label="Open incidents" value={stats.open_incidents} tone="var(--err)" />
        <Stat label="Investigations" value={stats.investigations} tone="var(--accent)" />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_380px]">
        <Panel>
          <PanelHeader
            title="Deploy activity · last 24 hours"
            right={
              <span className="flex gap-3 font-mono text-[10.5px] uppercase tracking-wider text-muted">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-[2px] bg-ok/60" /> ready
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-[2px] bg-err" /> failed
                </span>
              </span>
            }
          />
          <ActivityChart activity={data.activity} />
        </Panel>

        <Panel>
          <PanelHeader title="Active incidents" right={stats.open_incidents > 0 ? <Tag color="var(--err)">{stats.open_incidents} open</Tag> : null} />
          {data.incidents.length === 0 ? (
            <div className="flex h-24 items-center justify-center gap-2 text-[13px] text-muted">
              <CircleCheck size={15} className="text-ok" /> Nothing is on fire.
            </div>
          ) : (
            <ul>
              {data.incidents.slice(0, 3).map((i) => (
                <li key={i.id} className="flex items-center gap-3 border-b border-line-soft px-4 py-2.5 last:border-0">
                  <Siren size={14} className="shrink-0 text-err" />
                  <Link href={i.deployment_id ? `/console/deployments/${i.deployment_id}` : "/console/incidents"} className="min-w-0 flex-1 hover:underline">
                    <div className="truncate text-[13px]">{i.title}</div>
                    <div className="font-mono text-[11px] text-faint">
                      {i.service_name} · {timeAgo(i.opened_at, now)}
                    </div>
                  </Link>
                  {i.investigation_id ? (
                    <ButtonLink size="sm" href={`/console/investigations/${i.investigation_id}`}>
                      Report
                    </ButtonLink>
                  ) : (
                    <InvestigateButton incidentId={i.id} />
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <h2 className="label-mono mb-2 mt-6">Service health</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data.services.map((s) => (
          <ServiceCard key={s.id} s={s} now={now} />
        ))}
        {data.services.length === 0 && (
          <Panel className="sm:col-span-2 lg:col-span-3">
            <Empty title="No services yet" action={<ButtonLink href="/console/integrations" variant="primary">Connect a provider</ButtonLink>}>
              Connect Vercel or Railway and their projects show up here with health and deploy status.
            </Empty>
          </Panel>
        )}
      </div>

      <Panel className="mt-4">
        <PanelHeader
          title="Latest deploys"
          right={
            <Link href="/console/timeline" className="font-mono text-[11px] text-muted hover:text-fg">
              view all →
            </Link>
          }
        />
        {data.deployments.length === 0 ? <Empty title="No deploys recorded yet" /> : data.deployments.map((d) => <DeployRow key={d.id} d={d} now={now} />)}
      </Panel>
    </>
  );
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-[78px] rounded-xl" />
      <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
        <Skeleton className="h-36 rounded-xl" />
        <Skeleton className="h-36 rounded-xl" />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-32 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}
