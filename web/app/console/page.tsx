"use client";

import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { ArrowRight, BellOff, CircleCheck, Pencil, Siren, Star } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { mutate } from "swr";
import { DeployRow, InvestigateButton, useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { useToast } from "@/components/console/toast";
import { Button, ButtonLink, Empty, HealthBadge, Panel, PanelHeader, Skeleton, StatusBadge, Tag } from "@/components/ui/primitives";
import { ProviderTile } from "@/components/ui/provider";
import { api, ApiError, useApi } from "@/lib/api";
import { cn, timeAgo } from "@/lib/format";
import type { Overview, Service, ServiceUpdate } from "@/lib/types";

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

const SLOTS = 24;

/** Pin (first) or mute (last) a service. The card moves at once; the API confirms after. */
function useRank(s: Service) {
  const toast = useToast();
  return async (change: ServiceUpdate) => {
    // Pinned and muted exclude each other, as on the server.
    const next = { ...s, ...change, ...(change.pinned ? { muted: false } : {}), ...(change.muted ? { pinned: false } : {}) };
    void mutate("/overview", (cur?: Overview) => (cur ? { ...cur, services: cur.services.map((x) => (x.id === s.id ? next : x)) } : cur), { revalidate: false });
    try {
      await api(`/services/${s.id}`, { method: "PATCH", json: change });
    } catch (e) {
      toast.error(`Could not update ${s.name}`, (e as ApiError).message);
    } finally {
      void mutate("/overview");
    }
  };
}

function RankButton({ on, label, onClick, children }: { on: boolean; label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      aria-label={label}
      title={label}
      className={cn(
        "grid size-6 place-items-center rounded-md transition-[opacity,color,background-color] hover:bg-raised focus-visible:opacity-100",
        on ? "text-fg" : "text-faint opacity-0 hover:text-fg group-hover:opacity-100 pointer-coarse:opacity-100",
      )}
    >
      {children}
    </button>
  );
}

function ServiceCard({ s, now }: { s: Service; now: number }) {
  const [editing, setEditing] = useState(false);
  const rank = useRank(s);
  const checks = s.health_history.slice(-SLOTS);
  const monitored = !!s.health_url;
  const max = Math.max(1, ...checks.map((h) => h.latency_ms ?? 0));
  const passed = checks.filter((h) => h.ok).length;
  const host = s.health_url ? s.health_url.replace(/^https?:\/\//, "").replace(/\/$/, "") : null;

  return (
    <div className={cn("panel group flex h-full flex-col p-4 transition-opacity duration-300", s.muted && "opacity-50 focus-within:opacity-100 hover:opacity-100", s.pinned && "border-[var(--line-strong)]")}>
      <div className="flex items-start gap-3">
        <ProviderTile provider={s.provider} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13.5px] font-medium">{s.name}</div>
          <div className="truncate font-mono text-[11px] text-faint">{s.repo ?? s.external_id}</div>
        </div>
        <div className="-mr-1 -mt-0.5 flex shrink-0 items-center">
          <RankButton on={s.pinned} label={s.pinned ? `Unpin ${s.name}` : `Pin ${s.name} to the top`} onClick={() => rank({ pinned: !s.pinned })}>
            <Star size={13} fill={s.pinned ? "currentColor" : "none"} />
          </RankButton>
          <RankButton on={s.muted} label={s.muted ? `Unmute ${s.name}` : `Mute ${s.name} and move it to the end`} onClick={() => rank({ muted: !s.muted })}>
            <BellOff size={13} />
          </RankButton>
        </div>
        {monitored ? (
          checks.length > 0 ? (
            <HealthBadge health={s.health} />
          ) : (
            <span className="font-mono text-[11px] uppercase tracking-wider text-faint">first check soon</span>
          )
        ) : (
          <span className="font-mono text-[11px] uppercase tracking-wider text-faint">not monitored</span>
        )}
      </div>

      {/* Always 24 slots, newest on the right: height is response time, colour is pass or fail. */}
      <div className="mt-4 flex h-8 items-end gap-[3px]" role="img" aria-label={monitored ? `${passed} of ${checks.length} recent health checks passed` : "Health checks are off"}>
        {Array.from({ length: SLOTS - checks.length }, (_, i) => (
          <span key={`empty-${i}`} className="h-px flex-1 bg-line" />
        ))}
        {checks.map((h, i) => (
          <span
            key={i}
            title={`${new Date(h.checked_at).toLocaleTimeString()} · ${h.status_code ?? "no response"} · ${h.latency_ms != null ? `${h.latency_ms}ms` : "timed out"}`}
            className="flex-1 rounded-[1px] transition-opacity hover:opacity-60"
            style={{ height: `${h.ok ? 25 + ((h.latency_ms ?? 0) / max) * 75 : 100}%`, background: h.ok ? "color-mix(in oklab, var(--ok) 70%, transparent)" : "var(--err)" }}
          />
        ))}
      </div>

      <div className="mt-3 flex min-h-5 items-center justify-between gap-3 font-mono text-[11px] text-muted">
        {editing ? null : monitored ? (
          <span className="flex min-w-0 items-center gap-2">
            {checks.length > 0 && (
              <span className="shrink-0 text-fg/90">
                {Math.round((passed / checks.length) * 100)}% · {s.latency_ms != null ? `${s.latency_ms}ms` : "no response"}
              </span>
            )}
            <a href={s.health_url!} target="_blank" rel="noreferrer" className="truncate text-faint hover:text-fg" title={s.health_url!}>
              {host}
            </a>
            <button onClick={() => setEditing(true)} className="shrink-0 text-faint opacity-0 transition-opacity hover:text-fg focus:opacity-100 group-hover:opacity-100 pointer-coarse:opacity-100" aria-label={`Change the health URL of ${s.name}`}>
              <Pencil size={11} />
            </button>
          </span>
        ) : (
          <button onClick={() => setEditing(true)} className="text-muted underline decoration-line underline-offset-4 hover:text-fg hover:decoration-fg">
            Set a health URL
          </button>
        )}
        {!editing && (
          <span className="flex shrink-0 items-center gap-2">
            {s.last_deploy_status ? (
              <>
                <StatusBadge status={s.last_deploy_status} />
                <span className="text-faint" title={s.last_deploy_at ? new Date(s.last_deploy_at).toLocaleString() : undefined}>
                  {timeAgo(s.last_deploy_at, now)}
                </span>
              </>
            ) : (
              <span className="text-faint">no deploys seen</span>
            )}
          </span>
        )}
      </div>

      {editing && <HealthUrlEditor s={s} onDone={() => setEditing(false)} />}
    </div>
  );
}

/** Inline editor for the URL the uptime checker probes. */
function HealthUrlEditor({ s, onDone }: { s: Service; onDone: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState(s.health_url ?? "");
  const [busy, setBusy] = useState(false);

  // "" turns checks off for good; null hands the choice back to the provider sync.
  const save = async (value: string | null, message: string) => {
    setBusy(true);
    try {
      await api(`/services/${s.id}`, { method: "PATCH", json: { health_url: value } });
      await mutate("/overview");
      toast.ok(message, s.name);
      onDone();
    } catch (e) {
      toast.error("Could not save the health URL", (e as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <form
      className="mt-1 space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (url.trim()) save(url.trim(), "Health URL saved");
      }}
    >
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://example.com/healthz"
        type="url"
        autoFocus
        aria-label={`Health URL for ${s.name}`}
        className="h-8 w-full rounded-md border border-line bg-bg px-2.5 font-mono text-[12px] outline-none placeholder:text-faint focus:border-[var(--line-strong)]"
      />
      <div className="flex items-center gap-1.5">
        <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!url.trim()}>
          Save
        </Button>
        <Button type="button" size="sm" disabled={busy} onClick={() => save("", "Health checks turned off")}>
          Turn off
        </Button>
        {s.provider === "vercel" && (
          <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => save(null, "Using the production URL after the next sync")} title="Use this project's production URL">
            Automatic
          </Button>
        )}
        <Button type="button" size="sm" variant="ghost" className="ml-auto" disabled={busy} onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

/** Pinned first and muted last; in between, anything down, then whatever shipped most recently. */
function byUrgency(a: Service, b: Service) {
  const place = (s: Service) => (s.pinned ? 0 : s.muted ? 2 : 1);
  const rank = (s: Service) => (s.health === "down" ? 0 : s.last_deploy_status === "failed" ? 1 : 2);
  return place(a) - place(b) || rank(a) - rank(b) || (b.last_deploy_at ?? "").localeCompare(a.last_deploy_at ?? "") || a.name.localeCompare(b.name);
}

const FIRST_SERVICES = 9;

function ServiceGrid({ services, now }: { services: Service[]; now: number }) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(() => [...services].sort(byUrgency), [services]);
  const shown = all ? sorted : sorted.slice(0, FIRST_SERVICES);
  const monitored = services.filter((s) => s.health_url).length;
  const down = services.filter((s) => s.health === "down").length;
  const pinned = services.filter((s) => s.pinned).length;
  const muted = services.filter((s) => s.muted).length;

  return (
    <>
      <div className="mb-2 mt-6 flex items-end justify-between gap-3">
        <h2 className="label-mono">Service health</h2>
        <span className="font-mono text-[11px] text-faint">
          {monitored} of {services.length} monitored
          {pinned > 0 && ` · ${pinned} pinned`}
          {muted > 0 && ` · ${muted} muted`}
          {down > 0 && <span className="text-err"> · {down} down</span>}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((s) => (
          // `layout` slides a card to its new place when it is pinned or muted.
          <motion.div key={s.id} layout="position" transition={{ duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}>
            <ServiceCard s={s} now={now} />
          </motion.div>
        ))}
      </div>
      {sorted.length > FIRST_SERVICES && (
        <button onClick={() => setAll((v) => !v)} className="mt-3 flex h-9 w-full items-center justify-center rounded-lg border border-line font-mono text-[11px] uppercase tracking-wider text-muted transition-colors hover:bg-raised hover:text-fg">
          {all ? "Show fewer" : `Show all ${sorted.length} services`}
        </button>
      )}
    </>
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

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Services" value={stats.services} />
        <Stat label="Down" value={stats.services_down} tone="var(--err)" />
        <Stat label="Deploys" value={stats.deploys_24h} hint="24h" />
        <Stat label="Failed" value={stats.failed_24h} tone="var(--err)" hint="24h" />
        <Stat label="Open incidents" value={stats.open_incidents} tone="var(--err)" />
        <Stat label="Investigations" value={stats.investigations} tone="var(--accent)" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
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

      {data.services.length > 0 ? (
        <ServiceGrid services={data.services} now={now} />
      ) : (
        <Panel className="mt-6">
          <Empty title="No services monitored" action={<ButtonLink href="/console/integrations" variant="primary">Open integrations</ButtonLink>}>
            Connect a provider, or choose which of its services to monitor, and they show up here with health and deploy status.
          </Empty>
        </Panel>
      )}

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
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <Skeleton className="h-36 rounded-xl" />
        <Skeleton className="h-36 rounded-xl" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-32 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}
