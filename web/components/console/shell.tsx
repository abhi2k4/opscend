"use client";

import { Command } from "cmdk";
import {
  Activity,
  Bell,
  Blocks,
  BookOpen,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareText,
  Rocket,
  Search,
  Siren,
  Sparkles,
  Unplug,
  Webhook,
  X,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { mutate } from "swr";
import { Button, Dot, Kbd, Spinner, Tag } from "@/components/ui/primitives";
import { ProviderIcon, Wordmark } from "@/components/ui/provider";
import { api, useApi } from "@/lib/api";
import { cn, firstLine, shortSha } from "@/lib/format";
import { API_DOCS_URL } from "@/lib/site";
import type { Deployment, Incident, SystemInfo, User } from "@/lib/types";
import { NotificationBell } from "./notifications";
import { ToastProvider } from "./toast";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  key: string; // second key of the "g <key>" shortcut
  exact?: boolean;
}

const NAV: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Operate",
    items: [
      { href: "/console", label: "Overview", icon: LayoutDashboard, key: "o", exact: true },
      { href: "/console/ask", label: "Ask Opscend", icon: MessageSquareText, key: "a" },
      { href: "/console/timeline", label: "Timeline", icon: Activity, key: "t" },
      { href: "/console/incidents", label: "Incidents", icon: Siren, key: "i" },
      { href: "/console/investigations", label: "Investigations", icon: Sparkles, key: "n" },
      { href: "/console/notifications", label: "Notifications", icon: Bell, key: "b" },
    ],
  },
  {
    heading: "Develop",
    items: [
      { href: "/console/integrations", label: "Integrations", icon: Blocks, key: "p" },
      { href: "/console/events", label: "Event inspector", icon: Webhook, key: "e" },
      { href: "/console/chaos", label: "Chaos lab", icon: FlaskConical, key: "c" },
    ],
  },
];

const ALL_ITEMS = NAV.flatMap((g) => g.items);

export function ConsoleShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const me = useApi<User>("/auth/me", { revalidateOnFocus: false });
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [drawer, setDrawer] = useState(false);

  // Auth gate: 401 → login, keeping the page the user wanted.
  useEffect(() => {
    if (me.error?.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [me.error, router, pathname]);

  useEffect(() => setDrawer(false), [pathname]);

  // ⌘K, and "g then <key>" navigation.
  const lastG = useRef(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        setPaletteOpen(true);
      } else if (e.key === "g") {
        lastG.current = Date.now();
      } else if (Date.now() - lastG.current < 900) {
        const hit = ALL_ITEMS.find((i) => i.key === e.key);
        if (hit) router.push(hit.href);
        lastG.current = 0;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  if (me.error && me.error.status !== 401) return <ApiOffline message={me.error.message} onRetry={() => me.mutate()} />;
  if (!me.data) {
    return (
      <div className="grid h-dvh place-items-center text-muted">
        <Spinner className="size-4" />
      </div>
    );
  }

  return (
    <ToastProvider>
      <div className="flex h-dvh overflow-hidden">
        <aside className="hidden w-[232px] shrink-0 border-r border-line bg-surface md:block">
          <Sidebar user={me.data} />
        </aside>

        <AnimatePresence>
          {drawer && (
            <>
              <motion.div className="fixed inset-0 z-40 bg-black/70 md:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawer(false)} />
              <motion.aside
                className="fixed inset-y-0 left-0 z-50 w-[260px] border-r border-line bg-surface md:hidden"
                initial={{ x: -280 }}
                animate={{ x: 0 }}
                exit={{ x: -280 }}
                transition={{ type: "spring", damping: 30, stiffness: 320 }}
              >
                <Sidebar user={me.data} />
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line px-4">
            <button className="grid size-8 place-items-center rounded-md text-muted hover:bg-raised md:hidden" onClick={() => setDrawer(true)} aria-label="Open navigation">
              <Menu size={16} />
            </button>
            <Crumbs pathname={pathname} />
            <button
              onClick={() => setPaletteOpen(true)}
              aria-label="Search or jump to a page"
              className="ml-auto flex size-8 shrink-0 items-center justify-center gap-2 rounded-lg border border-line bg-surface text-[12.5px] text-muted transition-colors hover:border-[var(--line-strong)] hover:text-fg sm:w-full sm:max-w-[200px] sm:shrink lg:max-w-[280px] sm:justify-start sm:px-2.5"
            >
              <Search size={13} />
              <span className="hidden flex-1 truncate text-left sm:block">Search or jump to…</span>
              <Kbd className="max-sm:hidden">⌘</Kbd>
              <Kbd className="max-sm:hidden">K</Kbd>
            </button>
            <NotificationBell />
            <a href={API_DOCS_URL} target="_blank" rel="noreferrer" className="hidden h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] text-muted hover:bg-raised hover:text-fg sm:inline-flex">
              <BookOpen size={13} /> API
            </a>
          </header>
          <main className="min-h-0 flex-1 overflow-y-auto">
            <motion.div key={pathname} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="mx-auto max-w-[1320px] p-4 sm:p-6">
              {children}
            </motion.div>
          </main>
        </div>
      </div>
      <Palette open={paletteOpen} setOpen={setPaletteOpen} />
    </ToastProvider>
  );
}

function Crumbs({ pathname }: { pathname: string }) {
  const parts = pathname.split("/").filter(Boolean).slice(1);
  return (
    <div className="flex min-w-0 flex-1 items-center gap-2 font-mono text-[12px]">
      <Link href="/console" className="shrink-0 text-muted hover:text-fg">
        console
      </Link>
      {parts.map((p, i) => (
        <span key={i} className="flex min-w-0 items-center gap-2">
          <span className="text-faint">/</span>
          {i < parts.length - 1 ? (
            <Link href={`/console/${parts.slice(0, i + 1).join("/")}`} className="truncate text-muted hover:text-fg">
              {p}
            </Link>
          ) : (
            <span className="truncate text-fg">{p.length > 18 ? `${p.slice(0, 14)}…` : p}</span>
          )}
        </span>
      ))}
    </div>
  );
}

function Sidebar({ user }: { user: User }) {
  const pathname = usePathname();
  const router = useRouter();
  const system = useApi<SystemInfo>("/system", { revalidateOnFocus: false });
  const incidents = useApi<Incident[]>("/incidents?status=open", { refreshInterval: 8000 });
  const openCount = incidents.data?.length ?? 0;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 items-center justify-between border-b border-line px-4">
        <Link href="/" aria-label="Opscend home">
          <Wordmark />
        </Link>
        {system.data?.demo_mode && <Tag color="var(--warn)">demo</Tag>}
      </div>

      <nav className="flex-1 space-y-5 overflow-y-auto p-2.5 pt-4">
        {NAV.map((group) => (
          <div key={group.heading}>
            <div className="label-mono mb-1.5 px-2 text-faint">{group.heading}</div>
            <ul className="space-y-px">
              {group.items.map((item) => {
                const on = item.exact ? pathname === item.href : pathname.startsWith(item.href);
                const deployOn = item.href === "/console/timeline" && pathname.startsWith("/console/deployments");
                const active = on || deployOn;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        "group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors",
                        active ? "text-fg" : "text-muted hover:bg-raised/60 hover:text-fg",
                      )}
                    >
                      {active && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-md border border-line bg-raised" transition={{ type: "spring", damping: 30, stiffness: 400 }} />}
                      <item.icon size={14} className={cn("relative", active && "text-accent")} />
                      <span className="relative flex-1">{item.label}</span>
                      {item.href === "/console/incidents" && openCount > 0 && (
                        <span className="relative grid h-4 min-w-4 place-items-center rounded-sm bg-err/15 px-1 font-mono text-[10px] text-err">{openCount}</span>
                      )}
                      <span className="relative hidden gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 lg:flex">
                        <Kbd>g</Kbd>
                        <Kbd>{item.key}</Kbd>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="space-y-2 border-t border-line p-3">
        <div className="rounded-lg border border-line bg-bg/60 p-2.5 font-mono text-[10.5px] leading-[1.9] text-muted">
          <div className="flex items-center justify-between">
            <span className="uppercase tracking-wider text-faint">investigator</span>
            {system.data ? (
              <span className="flex items-center gap-1.5" style={{ color: system.data.ai.configured ? "var(--ok)" : "var(--warn)" }}>
                <Dot color="currentColor" className="scale-75" />
                {system.data.ai.configured ? "ready" : "no key"}
              </span>
            ) : (
              <span>…</span>
            )}
          </div>
          <div className="truncate" title={system.data?.ai.model}>
            {system.data ? `${system.data.ai.provider} · ${system.data.ai.model}` : "—"}
          </div>
          <div className="flex justify-between text-faint">
            <span>queue {system.data?.queue ?? "—"}</span>
            <span>{system.data?.database ?? "—"}</span>
            <span>v{system.data?.version ?? "—"}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 px-1">
          <span className="grid size-6 shrink-0 place-items-center rounded-md bg-raised font-mono text-[10px] uppercase text-muted">{user.email[0]}</span>
          <span className="min-w-0 flex-1 truncate text-[12px] text-muted">{user.email}</span>
          <button
            title="Sign out"
            aria-label="Sign out"
            className="grid size-6 place-items-center rounded-md text-faint hover:bg-raised hover:text-fg"
            onClick={async () => {
              await api("/auth/logout", { method: "POST" }).catch(() => {});
              await mutate(() => true, undefined, { revalidate: false });
              router.replace("/login");
            }}
          >
            <LogOut size={13} />
          </button>
        </div>
      </div>
    </div>
  );
}

function ApiOffline({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="grid h-dvh place-items-center p-6">
      <div className="panel w-full max-w-md p-7 text-center">
        <div className="mx-auto grid size-10 place-items-center rounded-lg border border-line bg-raised text-err">
          <Unplug size={18} />
        </div>
        <h1 className="mt-4 text-[16px] font-medium">The API is not answering</h1>
        <p className="mt-2 text-[13px] leading-relaxed text-muted">{message}</p>
        <pre className="code mt-4 rounded-lg border border-line bg-bg p-3 text-left text-muted">
          <span className="text-accent">$</span> make dev-api
        </pre>
        <Button className="mt-4" onClick={onRetry}>
          Retry
        </Button>
      </div>
    </div>
  );
}

// ───────────────────────────── command palette

function Palette({ open, setOpen }: { open: boolean; setOpen: (o: boolean) => void }) {
  const router = useRouter();
  const deployments = useApi<Deployment[]>(open ? "/deployments?limit=12" : null);
  const [search, setSearch] = useState("");
  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);
  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };
  const question = search.trim();
  const item =
    "flex h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-[13px] text-muted data-[selected=true]:bg-raised data-[selected=true]:text-fg";

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      overlayClassName="fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm"
      contentClassName="fixed left-1/2 top-[16vh] z-[90] w-[min(600px,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-line bg-surface shadow-[0_30px_100px_rgb(0_0_0/0.9)]"
    >
      <div className="flex items-center gap-2.5 border-b border-line px-3.5">
        <Search size={14} className="text-faint" />
        <Command.Input value={search} onValueChange={setSearch} placeholder="Jump to a page, deploy or action, or ask a question…" className="h-11 flex-1 bg-transparent text-[14px] outline-none placeholder:text-faint" />
        <button onClick={() => setOpen(false)} className="text-faint hover:text-fg" aria-label="Close">
          <X size={14} />
        </button>
      </div>
      <Command.List className="max-h-[52vh] overflow-y-auto p-1.5 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:font-mono [&_[cmdk-group-heading]]:text-[10.5px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-faint">
        {question.length < 3 && <Command.Empty className="px-3 py-8 text-center text-[13px] text-muted">Nothing matches.</Command.Empty>}
        <Command.Group heading="Go to">
          {ALL_ITEMS.map((i) => (
            <Command.Item key={i.href} value={`go ${i.label}`} onSelect={() => go(i.href)} className={item}>
              <i.icon size={14} />
              <span className="flex-1">{i.label}</span>
              <Kbd>g</Kbd>
              <Kbd>{i.key}</Kbd>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Actions">
          <Command.Item value="break something chaos scenario" onSelect={() => go("/console/chaos")} className={item}>
            <FlaskConical size={14} /> Break a deploy on purpose
          </Command.Item>
          <Command.Item value="connect provider integration token" onSelect={() => go("/console/integrations")} className={item}>
            <Blocks size={14} /> Connect a provider
          </Command.Item>
          <Command.Item
            value="api reference openapi docs"
            onSelect={() => {
              setOpen(false);
              window.open(API_DOCS_URL, "_blank");
            }}
            className={item}
          >
            <BookOpen size={14} /> Open API reference
          </Command.Item>
        </Command.Group>
        {!!deployments.data?.length && (
          <Command.Group heading="Recent deploys">
            {deployments.data.map((d) => (
              <Command.Item key={d.id} value={`deploy ${d.service_name} ${d.commit_sha} ${d.commit_message} ${d.status} ${d.id}`} onSelect={() => go(`/console/deployments/${d.id}`)} className={item}>
                <ProviderIcon provider={d.provider} size={13} />
                <span className="shrink-0 text-fg">{d.service_name}</span>
                <span className="min-w-0 flex-1 truncate">{firstLine(d.commit_message)}</span>
                <span className="font-mono text-[11px]">{shortSha(d.commit_sha)}</span>
                <Dot color={d.status === "failed" ? "var(--err)" : d.status === "ready" ? "var(--ok)" : "var(--warn)"} />
              </Command.Item>
            ))}
          </Command.Group>
        )}
        {question.length >= 3 && (
          <Command.Group heading="Ask" forceMount>
            <Command.Item value="ask-opscend-question" forceMount onSelect={() => go(`/console/ask?q=${encodeURIComponent(question)}`)} className={item}>
              <MessageSquareText size={14} />
              <span className="shrink-0 text-fg">Ask Opscend:</span>
              <span className="min-w-0 flex-1 truncate">{question}</span>
              <Kbd>↵</Kbd>
            </Command.Item>
          </Command.Group>
        )}
      </Command.List>
      <div className="flex items-center gap-4 border-t border-line px-3.5 py-2 font-mono text-[10.5px] text-faint">
        <span className="flex items-center gap-1">
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd> navigate
        </span>
        <span className="flex items-center gap-1">
          <Kbd>↵</Kbd> open
        </span>
        <span className="ml-auto flex items-center gap-1">
          <Rocket size={11} /> opscend
        </span>
      </div>
    </Command.Dialog>
  );
}

/** Standard page title row used by every console screen. */
export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[20px] font-medium tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-[13px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
