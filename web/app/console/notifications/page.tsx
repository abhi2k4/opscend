"use client";

import { Bell, Mail, Send } from "lucide-react";
import { useState } from "react";
import { useNow } from "@/components/console/deploys";
import { KIND_META, markAllRead, NotificationRow } from "@/components/console/notifications";
import { PageHeader } from "@/components/console/shell";
import { useToast } from "@/components/console/toast";
import { Button, Dot, Empty, Panel, PanelHeader, Skeleton, Tag } from "@/components/ui/primitives";
import { api, ApiError, useApi } from "@/lib/api";
import { cn } from "@/lib/format";
import type { NotificationList, NotificationSettings } from "@/lib/types";

const ENV_EXAMPLE = `OPSCEND_SMTP_HOST=smtp.example.com
OPSCEND_SMTP_PORT=587
OPSCEND_SMTP_USERNAME=you@example.com
OPSCEND_SMTP_PASSWORD=app-password
OPSCEND_EMAIL_TO=you@example.com`;

export default function NotificationsPage() {
  const [onlyUnread, setOnlyUnread] = useState(false);
  const { data, error } = useApi<NotificationList>(`/notifications?limit=100${onlyUnread ? "&unread=true" : ""}`, { refreshInterval: 8000 });
  const settings = useApi<NotificationSettings>("/notifications/settings", { revalidateOnFocus: false });
  const toast = useToast();
  const now = useNow();
  const [sending, setSending] = useState(false);
  const email = settings.data?.email;

  const sendTest = async () => {
    setSending(true);
    try {
      await api("/notifications/test-email", { method: "POST" });
      toast.ok("Test email sent", email?.to_address ? `Check ${email.to_address}.` : undefined);
    } catch (e) {
      toast.error("Test email failed", (e as ApiError).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Notifications"
        description="Incidents, investigations and integration problems, as they happen."
        actions={
          <>
            <div className="flex rounded-lg border border-line p-0.5">
              {[false, true].map((u) => (
                <button key={String(u)} onClick={() => setOnlyUnread(u)} className={cn("h-7 rounded-md px-3 font-mono text-[11px] uppercase tracking-wider", onlyUnread === u ? "bg-raised text-fg" : "text-muted hover:text-fg")}>
                  {u ? "unread" : "all"}
                </button>
              ))}
            </div>
            <Button onClick={markAllRead} disabled={!data?.unread}>
              Mark all read
            </Button>
          </>
        }
      />

      <div className="grid items-start gap-4 xl:grid-cols-[1fr_380px]">
        <Panel>
          {!data && !error && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>}
          {error && !data && <Empty title="Could not load notifications">{error.message}</Empty>}
          {data?.items.length === 0 && (
            <Empty icon={<Bell size={18} />} title={onlyUnread ? "You're all caught up" : "No notifications yet"}>
              {onlyUnread ? "Nothing unread." : "A failed deploy, an opened incident or a finished investigation will appear here."}
            </Empty>
          )}
          {data?.items.map((n) => <NotificationRow key={n.id} n={n} now={now} />)}
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title="Email alerts"
              right={
                email ? (
                  <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider" style={{ color: email.configured ? "var(--ok)" : "var(--warn)" }}>
                    <Dot color="currentColor" className="scale-75" /> {email.configured ? "on" : "not set up"}
                  </span>
                ) : null
              }
            />
            {!email ? (
              <div className="p-4"><Skeleton className="h-24" /></div>
            ) : email.configured ? (
              <div>
                <dl className="divide-y divide-line-soft font-mono text-[12px]">
                  {[
                    ["Server", `${email.host}:${email.port} · ${email.security}`],
                    ["From", email.from_address],
                    ["To", email.to_address],
                  ].map(([k, v]) => (
                    <div key={k} className="grid grid-cols-[72px_1fr] gap-3 px-4 py-2.5">
                      <dt className="uppercase tracking-wider text-faint">{k}</dt>
                      <dd className="truncate text-fg/90">{v}</dd>
                    </div>
                  ))}
                </dl>
                <div className="border-t border-line p-4">
                  <Button variant="primary" loading={sending} onClick={sendTest} className="w-full">
                    {!sending && <Send size={13} />} Send a test email
                  </Button>
                </div>
              </div>
            ) : (
              <div className="p-4">
                <div className="flex items-start gap-3">
                  <Mail size={16} className="mt-0.5 shrink-0 text-muted" />
                  <p className="text-[13px] leading-relaxed text-muted">
                    Notifications show in the console already. To also get them by email, add your SMTP details to <code className="font-mono text-fg">.env</code> and
                    restart the API and worker.
                  </p>
                </div>
                <pre className="code mt-3 overflow-x-auto rounded-lg border border-line bg-bg p-3 text-[11.5px] text-fg/80">{ENV_EXAMPLE}</pre>
              </div>
            )}
          </Panel>

          <Panel>
            <PanelHeader title="What gets sent" />
            <ul>
              {settings.data?.kinds.map((kind) => {
                const meta = KIND_META[kind];
                const emailed = !!email?.configured && email.events.includes(kind);
                return (
                  <li key={kind} className="flex items-center gap-3 border-b border-line-soft px-4 py-2.5 text-[13px] last:border-0">
                    <meta.icon size={13} style={{ color: meta.color }} />
                    <span className="flex-1">{meta.label}</span>
                    <Tag color="var(--muted)">in app</Tag>
                    {emailed && <Tag color="var(--ok)">email</Tag>}
                  </li>
                );
              })}
            </ul>
            <p className="border-t border-line px-4 py-3 text-[12px] leading-relaxed text-muted">
              Choose which are emailed with <code className="font-mono text-fg">OPSCEND_EMAIL_EVENTS</code>.
            </p>
          </Panel>
        </div>
      </div>
    </>
  );
}
