"use client";

import { AnimatePresence, motion } from "motion/react";
import { Bell, CircleCheck, Plug, Siren, Sparkles, TriangleAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { api, useApi } from "@/lib/api";
import { cn, timeAgo } from "@/lib/format";
import type { Notification, NotificationKind, NotificationList } from "@/lib/types";
import { useNow } from "./deploys";
import { useToast } from "./toast";

export const KIND_META: Record<NotificationKind, { label: string; icon: LucideIcon; color: string }> = {
  incident_opened: { label: "Incident opened", icon: Siren, color: "var(--err)" },
  incident_resolved: { label: "Incident resolved", icon: CircleCheck, color: "var(--ok)" },
  investigation_completed: { label: "Investigation finished", icon: Sparkles, color: "var(--accent)" },
  investigation_failed: { label: "Investigation failed", icon: TriangleAlert, color: "var(--warn)" },
  integration_error: { label: "Integration error", icon: Plug, color: "var(--warn)" },
};

const LIST_KEY = "/notifications?limit=30";

/** Revalidate every notification query (bell and page). */
export const refreshNotifications = () => mutate((key) => typeof key === "string" && key.startsWith("/notifications?"));

export async function markRead(id: string) {
  await api(`/notifications/${id}/read`, { method: "POST" }).catch(() => {});
  await refreshNotifications();
}

export async function markAllRead() {
  await api("/notifications/read-all", { method: "POST" }).catch(() => {});
  await refreshNotifications();
}

export function NotificationRow({ n, now, onOpen, compact }: { n: Notification; now: number; onOpen?: () => void; compact?: boolean }) {
  const router = useRouter();
  const meta = KIND_META[n.kind] ?? { label: n.kind, icon: Bell, color: "var(--muted)" };
  const unread = !n.read_at;
  return (
    <button
      onClick={() => {
        if (unread) markRead(n.id);
        onOpen?.();
        if (n.link) router.push(n.link);
      }}
      className={cn("group flex w-full items-start gap-3 border-b border-line-soft px-4 text-left transition-colors last:border-0 hover:bg-raised/60", compact ? "py-3" : "py-3.5")}
    >
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-line bg-raised">
        <meta.icon size={13} style={{ color: meta.color }} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className={cn("min-w-0 flex-1 truncate text-[13px]", unread ? "font-medium text-fg" : "text-muted")}>{n.title}</span>
          <span className="shrink-0 font-mono text-[10.5px] text-faint">{timeAgo(n.created_at, now)}</span>
        </span>
        {n.body && <span className={cn("mt-0.5 block text-[12px] leading-relaxed text-muted", compact ? "line-clamp-2" : "line-clamp-3")}>{n.body}</span>}
        {!compact && (
          <span className="mt-1.5 flex items-center gap-3 font-mono text-[10.5px] uppercase tracking-wider text-faint">
            <span>{meta.label}</span>
            {n.email_status === "sent" && <span className="text-ok">emailed</span>}
            {n.email_status === "pending" && <span>email queued</span>}
            {n.email_status === "failed" && (
              <span className="normal-case tracking-normal text-err" title={n.email_error ?? undefined}>
                email failed{n.email_error ? `: ${n.email_error}` : ""}
              </span>
            )}
          </span>
        )}
      </span>
      <span className={cn("mt-2 size-1.5 shrink-0 rounded-full transition-opacity", unread ? "bg-accent" : "opacity-0")} aria-label={unread ? "Unread" : undefined} />
    </button>
  );
}

/** Top-bar bell: unread count, a dropdown of the latest notifications, and a toast when a new one lands. */
export function NotificationBell() {
  const { data } = useApi<NotificationList>(LIST_KEY, { refreshInterval: 8000 });
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const now = useNow();
  const unread = data?.unread ?? 0;

  // Toast notifications that arrive while the console is open (never the backlog on first load).
  const newest = useRef<string | null>(null);
  useEffect(() => {
    if (!data) return;
    const latest = data.items[0]?.created_at ?? "";
    if (newest.current !== null) {
      for (const n of data.items.filter((item) => item.created_at > newest.current! && !item.read_at).slice(0, 3)) {
        (n.severity === "critical" || n.severity === "warning" ? toast.error : toast.ok)(n.title, n.body ?? undefined);
      }
    }
    newest.current = latest > (newest.current ?? "") ? latest : (newest.current ?? "");
  }, [data, toast]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !wrap.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={wrap} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        aria-expanded={open}
        className={cn("relative grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-raised hover:text-fg", open && "bg-raised text-fg")}
      >
        <Bell size={15} />
        <AnimatePresence>
          {unread > 0 && (
            <motion.span
              key="badge"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0 }}
              transition={{ type: "spring", stiffness: 500, damping: 25 }}
              className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-err px-1 font-mono text-[9.5px] font-medium text-white"
            >
              {unread > 99 ? "99+" : unread}
            </motion.span>
          )}
        </AnimatePresence>
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.16 }}
            role="dialog"
            aria-label="Notifications"
            className="absolute right-0 top-10 z-50 w-[min(400px,calc(100vw-2rem))] origin-top-right overflow-hidden rounded-xl border border-line bg-surface shadow-[0_24px_80px_rgb(0_0_0/0.85)]"
          >
            <div className="flex h-10 items-center justify-between border-b border-line px-4">
              <span className="label-mono">Notifications{unread > 0 ? ` · ${unread} unread` : ""}</span>
              {unread > 0 && (
                <button onClick={markAllRead} className="font-mono text-[11px] text-muted hover:text-fg">
                  mark all read
                </button>
              )}
            </div>
            <div className="max-h-[420px] overflow-y-auto">
              {!data && <div className="px-4 py-8 text-center text-[13px] text-muted">Loading…</div>}
              {data?.items.length === 0 && (
                <div className="px-6 py-10 text-center">
                  <Bell size={18} className="mx-auto text-faint" />
                  <div className="mt-3 text-[13px] font-medium">Nothing yet</div>
                  <p className="mt-1 text-[12.5px] text-muted">Failed deploys, incidents and finished investigations show up here.</p>
                </div>
              )}
              {data?.items.slice(0, 8).map((n) => <NotificationRow key={n.id} n={n} now={now} compact onOpen={() => setOpen(false)} />)}
            </div>
            <Link href="/console/notifications" onClick={() => setOpen(false)} className="flex h-10 items-center justify-center border-t border-line font-mono text-[11px] text-muted transition-colors hover:bg-raised/60 hover:text-fg">
              all notifications and email settings →
            </Link>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
