"use client";

import { AnimatePresence, motion } from "motion/react";
import { ExternalLink, ListChecks, Plus, RefreshCw, ShieldCheck, Trash2, X, Zap } from "lucide-react";
import { useState } from "react";
import { mutate } from "swr";
import { useNow } from "@/components/console/deploys";
import { MonitorPanel } from "@/components/console/monitor-panel";
import { PageHeader } from "@/components/console/shell";
import { useToast } from "@/components/console/toast";
import { Button, CopyButton, Dot, Empty, Panel, PanelHeader, Skeleton, Spotlight, Tag } from "@/components/ui/primitives";
import { ProviderTile, providerName } from "@/components/ui/provider";
import { api, ApiError, useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { REPO_URL } from "@/lib/site";
import type { Capability, Integration, ProviderManifest, Service } from "@/lib/types";

const CAP_LABEL: Record<Capability, string> = {
  LIST_SERVICES: "services",
  LIST_DEPLOYS: "deploys",
  BUILD_LOGS: "build logs",
  RUNTIME_LOGS: "runtime logs",
  WEBHOOKS: "webhooks",
  COMMITS: "commits",
  COMMIT_DIFF: "diffs",
};

function Caps({ caps }: { caps: Capability[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {caps.map((c) => (
        <span key={c} className="rounded-sm border border-line bg-bg px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted">
          {CAP_LABEL[c] ?? c}
        </span>
      ))}
    </div>
  );
}

const STATUS_COLOR = { connected: "var(--ok)", error: "var(--err)", pending: "var(--warn)" } as const;

export default function IntegrationsPage() {
  const integrations = useApi<Integration[]>("/integrations");
  const catalog = useApi<ProviderManifest[]>("/integrations/catalog", { revalidateOnFocus: false });
  const toast = useToast();
  const now = useNow();
  const [connecting, setConnecting] = useState<ProviderManifest | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [choosing, setChoosing] = useState<Integration | null>(null);
  // Every service, including the ones monitoring is off for, to count them per integration.
  const services = useApi<Service[]>("/services?scope=all");
  const counts = new Map<string, { on: number; total: number }>();
  for (const s of services.data ?? []) {
    const c = counts.get(s.integration_id) ?? { on: 0, total: 0 };
    counts.set(s.integration_id, { on: c.on + (s.monitored ? 1 : 0), total: c.total + 1 });
  }

  const act = async (i: Integration, action: "test" | "sync" | "delete") => {
    if (action === "delete" && !window.confirm(`Disconnect ${providerName(i.provider)}? Its stored token is deleted. Recorded deploys stay.`)) return;
    setBusy(`${i.id}:${action}`);
    try {
      if (action === "delete") {
        await api(`/integrations/${i.id}`, { method: "DELETE" });
        toast.ok(`${providerName(i.provider)} disconnected`);
      } else {
        const res = await api<Integration>(`/integrations/${i.id}/${action}`, { method: "POST" });
        if (res.status === "error") toast.error(`${providerName(i.provider)}: ${action} failed`, res.status_detail ?? undefined);
        else toast.ok(action === "test" ? "Connection works" : "Sync complete", res.account_name ?? undefined);
      }
      await Promise.all([integrations.mutate(), services.mutate(), mutate("/overview")]);
    } catch (e) {
      toast.error(`Could not ${action} ${providerName(i.provider)}`, (e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  const available = catalog.data?.filter((m) => m.availability === "available") ?? [];
  const planned = catalog.data?.filter((m) => m.availability === "planned") ?? [];

  return (
    <>
      <PageHeader title="Integrations" description="Connect a provider by pasting a token. Tokens are encrypted at rest and never returned by the API." />

      <Panel>
        <PanelHeader title="Connected" right={<span className="label-mono flex items-center gap-1.5 text-faint"><ShieldCheck size={12} /> Fernet-encrypted</span>} />
        {!integrations.data && !integrations.error && <div className="space-y-2 p-4">{[0, 1].map((i) => <Skeleton key={i} className="h-14" />)}</div>}
        {integrations.error && !integrations.data && <Empty title="Could not load integrations">{integrations.error.message}</Empty>}
        {integrations.data?.length === 0 && <Empty title="Nothing connected yet">Pick a provider below and paste a token.</Empty>}
        {integrations.data?.map((i) => (
          <div key={i.id} className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line-soft px-4 py-3.5 last:border-0">
            <ProviderTile provider={i.provider} size={34} />
            <div className="min-w-[180px] flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px]">
                <span className="font-medium">{providerName(i.provider)}</span>
                <span className="min-w-0 truncate text-muted">{i.account_name}</span>
                {i.is_demo && <Tag color="var(--warn)">demo data</Tag>}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px] text-muted">
                <span className="flex items-center gap-1.5" style={{ color: STATUS_COLOR[i.status] }}>
                  <Dot color="currentColor" className="scale-75" /> {i.status}
                </span>
                <span className="whitespace-nowrap">token ••••{i.token_hint}</span>
                <span className="whitespace-nowrap text-faint">synced {timeAgo(i.last_synced_at, now)}</span>
              </div>
              {i.status_detail && <div className={`mt-1 text-[12px] ${i.status === "error" ? "text-err" : "text-warn"}`}>{i.status_detail}</div>}
            </div>
            <div className="hidden lg:block">
              <Caps caps={i.capabilities} />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {counts.has(i.id) && (
                <Button size="sm" onClick={() => setChoosing(i)} title="Choose which services are monitored">
                  <ListChecks size={12} /> Services
                  <span className="font-mono text-[11px] text-muted">
                    {counts.get(i.id)!.on}/{counts.get(i.id)!.total}
                  </span>
                </Button>
              )}
              <Button size="sm" loading={busy === `${i.id}:test`} disabled={i.is_demo} title={i.is_demo ? "Demo integrations have no real token" : undefined} onClick={() => act(i, "test")}>
                <Zap size={12} /> Test
              </Button>
              <Button size="sm" loading={busy === `${i.id}:sync`} disabled={i.is_demo} onClick={() => act(i, "sync")}>
                <RefreshCw size={12} /> Sync
              </Button>
              <Button size="sm" variant="ghost" loading={busy === `${i.id}:delete`} onClick={() => act(i, "delete")} aria-label="Disconnect">
                <Trash2 size={13} />
              </Button>
            </div>
          </div>
        ))}
      </Panel>

      <h2 className="label-mono mb-2 mt-7">Catalog · from the adapter registry</h2>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {!catalog.data && [0, 1, 2].map((i) => <Skeleton key={i} className="h-36 rounded-xl" />)}
        {available.map((m) => (
          <Spotlight key={m.provider} className="panel flex flex-col p-4">
            <div className="flex items-center gap-3">
              <ProviderTile provider={m.provider} size={34} />
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium">{m.name}</div>
                <div className="truncate font-mono text-[11px] text-faint">{m.token_label}</div>
              </div>
              <Tag color="var(--ok)">available</Tag>
            </div>
            <p className="mt-3 flex-1 text-[12.5px] leading-relaxed text-muted">{m.description}</p>
            <div className="mt-3">
              <Caps caps={m.capabilities} />
            </div>
            <Button className="mt-4" variant="primary" onClick={() => setConnecting(m)}>
              <Plus size={13} /> Connect {m.name}
            </Button>
          </Spotlight>
        ))}
        {planned.map((m) => (
          <div key={m.provider} className="panel flex flex-col border-dashed p-4 opacity-60">
            <div className="flex items-center gap-3">
              <ProviderTile provider={m.provider} size={34} />
              <div className="flex-1 text-[14px] font-medium">{m.name}</div>
              <Tag>planned</Tag>
            </div>
            <p className="mt-3 text-[12.5px] leading-relaxed text-muted">{m.description}</p>
          </div>
        ))}
        <a href={`${REPO_URL}/blob/main/docs/adding-a-provider.md`} target="_blank" rel="noreferrer" className="panel flex flex-col justify-between border-dashed p-4 transition-colors hover:border-accent/50">
          <span className="grid size-[34px] place-items-center rounded-md border border-dashed border-accent/50 text-accent">
            <Plus size={15} />
          </span>
          <div className="mt-4">
            <div className="flex items-center gap-1.5 text-[14px] font-medium">
              Write an adapter <ExternalLink size={12} className="text-faint" />
            </div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
              One file in <code className="font-mono text-fg">api/app/integrations/</code> and one registry line. It appears in this catalog automatically.
            </p>
          </div>
        </a>
      </div>

      <AnimatePresence>
        {connecting && (
          <ConnectDialog
            manifest={connecting}
            onClose={() => setConnecting(null)}
            onDone={async (i) => {
              setConnecting(null);
              toast.ok(`${providerName(i.provider)} connected`, i.account_name ?? undefined);
              const [, all] = await Promise.all([integrations.mutate(), services.mutate(), mutate("/overview")]);
              // Straight to the choice when the account has more than one service.
              if ((all ?? []).filter((s) => s.integration_id === i.id).length > 1) setChoosing(i);
            }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {choosing && (
          <MonitorPanel
            integration={choosing}
            now={now}
            onClose={() => setChoosing(null)}
            onSaved={async (saved) => {
              setChoosing(null);
              const on = saved.filter((s) => s.monitored).length;
              toast.ok(`Monitoring ${on} of ${saved.length} services`, providerName(choosing.provider));
              await Promise.all([services.mutate(), mutate("/overview")]);
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

function ConnectDialog({ manifest: m, onClose, onDone }: { manifest: ProviderManifest; onClose: () => void; onDone: (i: Integration) => void }) {
  const [token, setToken] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const webhookUrl = m.webhook_path && typeof window !== "undefined" ? `${window.location.origin}${m.webhook_path}` : null;
  const input = "h-9 w-full rounded-lg border border-line bg-bg px-3 font-mono text-[12.5px] outline-none placeholder:text-faint focus:border-accent/60";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onDone(await api<Integration>("/integrations", { method: "POST", json: { provider: m.provider, token, config } }));
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <motion.div className="fixed inset-0 z-[70] grid grid-cols-1 place-items-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <motion.form
        onSubmit={submit}
        role="dialog"
        aria-modal
        aria-label={`Connect ${m.name}`}
        initial={{ opacity: 0, y: 16, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: 0.2 }}
        className="panel w-full max-w-[460px] bg-surface p-5 shadow-[0_30px_100px_rgb(0_0_0/0.9)]"
      >
        <div className="flex items-center gap-3">
          <ProviderTile provider={m.provider} size={34} />
          <div className="flex-1">
            <div className="text-[15px] font-medium">Connect {m.name}</div>
            <div className="text-[12px] text-muted">Validated, then encrypted before it is stored.</div>
          </div>
          <button type="button" onClick={onClose} className="text-faint hover:text-fg" aria-label="Close">
            <X size={15} />
          </button>
        </div>

        <label className="mt-5 block">
          <span className="label-mono mb-1.5 flex items-center justify-between">
            {m.token_label}
            {m.token_help_url && (
              <a href={m.token_help_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 normal-case tracking-normal text-accent hover:underline">
                where do I get this? <ExternalLink size={10} />
              </a>
            )}
          </span>
          <input className={input} type="password" autoComplete="off" required value={token} onChange={(e) => setToken(e.target.value)} placeholder="paste token" autoFocus />
        </label>
        {m.config_fields.map((f) => (
          <label key={f.key} className="mt-3 block">
            <span className="label-mono mb-1.5 block">
              {f.label} {!f.required && <span className="text-faint">· optional</span>}
            </span>
            <input className={input} type={/secret|token|password/i.test(f.key) ? "password" : "text"} autoComplete="off" required={f.required} placeholder={f.placeholder} value={config[f.key] ?? ""} onChange={(e) => setConfig((c) => ({ ...c, [f.key]: e.target.value }))} />
          </label>
        ))}

        {webhookUrl && (
          <div className="mt-4 rounded-lg border border-line bg-bg/60 p-3">
            <div className="label-mono mb-1">Webhook URL · optional, polling works without it</div>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg/80">{webhookUrl}</code>
              <CopyButton value={webhookUrl} />
            </div>
          </div>
        )}

        {error && (
          <div role="alert" className="mt-4 rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12.5px] text-err">
            {error}
          </div>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Test & connect
          </Button>
        </div>
      </motion.form>
    </motion.div>
  );
}
