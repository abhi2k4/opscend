"use client";

import { Check, Search, X } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Skeleton, StatusBadge } from "@/components/ui/primitives";
import { ProviderTile, providerName } from "@/components/ui/provider";
import { api, ApiError, useApi } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Integration, MonitoredServices, Service } from "@/lib/types";

const SEARCH_FROM = 7;

/** Slides in from the right: pick which of an integration's services Opscend watches. */
export function MonitorPanel({ integration: i, now, onClose, onSaved }: { integration: Integration; now: number; onClose: () => void; onSaved: (services: Service[]) => void }) {
  const path = `/integrations/${i.id}/services`;
  const { data, error } = useApi<Service[]>(path, { revalidateOnFocus: false, keepPreviousData: false });
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  // The selection starts as what is stored, and is the user's from then on.
  const chosen = useMemo(() => picked ?? new Set((data ?? []).filter((s) => s.monitored).map((s) => s.id)), [picked, data]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data ?? []).filter((s) => !q || s.name.toLowerCase().includes(q) || (s.repo ?? "").toLowerCase().includes(q));
  }, [data, query]);
  const changed = !!data && data.some((s) => s.monitored !== chosen.has(s.id));
  const allShown = shown.length > 0 && shown.every((s) => chosen.has(s.id));

  useEffect(() => {
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (!next.delete(id)) next.add(id);
    setPicked(next);
  };
  const toggleShown = () => {
    const next = new Set(chosen);
    for (const s of shown) {
      if (allShown) next.delete(s.id);
      else next.add(s.id);
    }
    setPicked(next);
  };

  const save = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const body: MonitoredServices = { service_ids: [...chosen] };
      onSaved(await api<Service[]>(path, { method: "PUT", json: body }));
    } catch (e) {
      setFailure((e as ApiError).message);
      setBusy(false);
    }
  };

  return (
    <motion.div className="fixed inset-0 z-[70] bg-black/60 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <motion.div
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal
        aria-label={`Services monitored on ${providerName(i.provider)}`}
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        className="absolute inset-y-0 right-0 flex w-full max-w-[440px] flex-col border-l border-line bg-surface outline-none"
      >
        <header className="flex items-center gap-3 border-b border-line px-5 py-4">
          <ProviderTile provider={i.provider} size={34} />
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-medium">Monitored services</div>
            <div className="truncate text-[12px] text-muted">
              {providerName(i.provider)} · {i.account_name}
            </div>
          </div>
          <button type="button" onClick={onClose} className="grid size-8 place-items-center text-faint transition-colors hover:text-fg" aria-label="Close">
            <X size={16} />
          </button>
        </header>

        <p className="border-b border-line-soft px-5 py-3 text-[12.5px] leading-relaxed text-muted">
          Only the services you tick are watched and shown in the console. The rest are not polled, open no incidents and send no alerts. Their history is kept for when you turn them back on.
        </p>

        {data && data.length > 0 && (
          <div className="flex items-center gap-3 border-b border-line-soft px-5 py-2.5">
            {data.length >= SEARCH_FROM && (
              <label className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-lg border border-line bg-bg px-2.5 focus-within:border-accent/60">
                <Search size={13} className="shrink-0 text-faint" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter services" aria-label="Filter services" className="min-w-0 flex-1 bg-transparent text-[12.5px] outline-none placeholder:text-faint" />
              </label>
            )}
            <button type="button" onClick={toggleShown} disabled={shown.length === 0} className="ml-auto shrink-0 font-mono text-[11px] uppercase tracking-wider text-muted transition-colors hover:text-fg disabled:opacity-40">
              {allShown ? "Clear all" : "Select all"}
            </button>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!data && !error && <div className="space-y-2 p-5">{[0, 1, 2, 3].map((n) => <Skeleton key={n} className="h-12" />)}</div>}
          {error && !data && <Empty title="Could not load services">{error.message}</Empty>}
          {data?.length === 0 && <Empty title="No services found">This account has no projects or services yet. Run a sync after you create one.</Empty>}
          {data && data.length > 0 && shown.length === 0 && <Empty title="Nothing matches that filter" />}
          <ul>
            {shown.map((s) => {
              const on = chosen.has(s.id);
              return (
                <li key={s.id} className="border-b border-line-soft last:border-0">
                  <label className={`flex cursor-pointer items-center gap-3 px-5 py-3 transition-colors hover:bg-bg/60 ${on ? "" : "text-muted"}`}>
                    <input type="checkbox" checked={on} onChange={() => toggle(s.id)} className="peer sr-only" />
                    <span aria-hidden className={`grid size-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-accent/60 ${on ? "border-accent bg-accent text-bg" : "border-line bg-bg text-transparent"}`}>
                      <Check size={12} strokeWidth={3} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={`block truncate text-[13.5px] ${on ? "text-fg" : ""}`}>{s.name}</span>
                      <span className="block truncate font-mono text-[11px] text-faint">{s.repo ?? "no linked repo"}</span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      {s.last_deploy_status ? <StatusBadge status={s.last_deploy_status} /> : <span className="font-mono text-[11px] text-faint">no deploys</span>}
                      {s.last_deploy_at && <span className="font-mono text-[10.5px] text-faint">{timeAgo(s.last_deploy_at, now)}</span>}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>

        {failure && (
          <div role="alert" className="border-t border-err/30 bg-err/10 px-5 py-2 text-[12.5px] text-err">
            {failure}
          </div>
        )}
        <footer className="flex items-center gap-2 border-t border-line px-5 py-3.5">
          <span className="flex-1 font-mono text-[11.5px] text-muted" aria-live="polite">
            {data ? `${chosen.size} of ${data.length} monitored` : ""}
          </span>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" variant="primary" loading={busy} disabled={!changed} onClick={save}>
            Save
          </Button>
        </footer>
      </motion.div>
    </motion.div>
  );
}
