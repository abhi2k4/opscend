"use client";

import { ArrowRight, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { mutate } from "swr";
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Sherlog } from "@/components/ui/sherlog";
import { api } from "@/lib/api";
import { DOCS_URL } from "@/lib/site";
import type { Incident } from "@/lib/types";
import { QuickstartCommands } from "./self-host";

/**
 * The guided tour of the demo. It never blocks the page: the highlighted part stays
 * clickable, so a visitor does each step for real (breaks a deploy, opens the report)
 * or presses Next and is taken there.
 */

const KEY = "opscend-tour";
export const BROKE_EVENT = "opscend:broke";

interface Saved {
  step: number; // -1 = not running
  seen: boolean; // the welcome card has been answered once
  deployment?: string;
  incident?: string;
}

interface Ctx {
  saved: Saved;
  where: (ctx: Saved) => Promise<string>;
}

interface Step {
  /** The page this step is shown on. */
  on: RegExp;
  /** `data-tour` value of the element to point at; none = a card in the corner. */
  target?: string;
  title: string;
  body: ReactNode;
  /** What the visitor is asked to do themselves, if anything. */
  task?: string;
  /** Where Next goes when the following step lives on another page. */
  next?: Ctx["where"];
  nextLabel?: string;
  /** Next does the task for the visitor instead of moving on (the task's own event moves on). */
  act?: () => Promise<void>;
}

async function incidentOf(saved: Saved): Promise<Incident | null> {
  try {
    if (saved.incident) return await api<Incident>(`/incidents/${saved.incident}`);
    const open = await api<Incident[]>("/incidents?status=open");
    return open[0] ?? (await api<Incident[]>("/incidents"))[0] ?? null;
  } catch {
    return null;
  }
}

const STEPS: Step[] = [
  {
    on: /^\/console$/,
    target: "stats",
    title: "Everything in one place",
    body: "Deploys from every platform, open incidents and investigations, counted across all your services. This instance runs on sample data for a fictional storefront.",
  },
  {
    on: /^\/console$/,
    target: "services",
    title: "Service health",
    body: "Each bar is a health check: taller is slower, red is a failure. Star a service to keep it first, or mute one to move it to the end.",
    task: "Try the star on a card.",
    next: async () => "/console/chaos",
    nextLabel: "Now break something",
  },
  {
    on: /^\/console\/chaos$/,
    target: "break",
    title: "Break a deploy on purpose",
    body: "Each card pushes a bad commit and a failed deploy through the same pipeline a real webhook takes.",
    task: "Click Break it on any card.",
    nextLabel: "Break one for me",
    act: async () => {
      const scenario_id = "bad-env-var";
      const res = await api<{ deployment_id: string; incident_id: string }>("/demo/break", { method: "POST", json: { scenario_id } });
      window.dispatchEvent(new CustomEvent(BROKE_EVENT, { detail: { ...res, scenario_id } }));
      await mutate((key) => typeof key === "string" && !key.startsWith("/system") && !key.startsWith("/auth"));
    },
  },
  {
    on: /^\/console\/chaos$/,
    target: "broken",
    title: "It failed. Opscend noticed.",
    body: "An incident opened and the investigator started by itself, with no one paged yet. That is the whole idea: the alert arrives with the cause attached.",
    next: async () => "/console/incidents",
    nextLabel: "See the incident",
  },
  {
    on: /^\/console\/incidents$/,
    target: "incident",
    title: "One incident per broken service",
    body: "Opened automatically when a deploy fails or a service fails two health checks, and closed when the next deploy is healthy.",
    task: "Open its Report.",
    next: async (saved) => {
      const incident = await incidentOf(saved);
      return incident?.investigation_id ? `/console/investigations/${incident.investigation_id}` : "/console/investigations";
    },
    nextLabel: "Open the report",
  },
  {
    on: /^\/console\/investigations\/[^/]+$/,
    target: "trace",
    title: "How it worked it out",
    body: "Every step is recorded: what the investigator asked for and what came back. Its tools can only read. In this demo the steps are scripted; on your own install a model chooses them.",
    task: "Click a step to see its input and output.",
  },
  {
    on: /^\/console\/investigations\/[^/]+$/,
    target: "report",
    title: "The cause, with proof",
    body: "The likely cause, the commit behind it and a suggested fix. Each piece of evidence is a real log line or commit that was checked against what the tools returned. No evidence, no verdict.",
    task: "Click a log line to jump to it.",
    next: async (saved) => {
      const incident = await incidentOf(saved);
      const deployment = saved.deployment ?? incident?.deployment_id;
      return deployment ? `/console/deployments/${deployment}?tab=changes` : "/console/timeline";
    },
    nextLabel: "See what changed",
  },
  {
    on: /^\/console\/deployments\/[^/]+$/,
    target: "tabs",
    title: "What changed since it last worked",
    body: "Build logs, runtime logs and the diff for this deploy, plus the files changed since the last healthy one. The file the failure points at is marked.",
    task: "Switch between the tabs.",
    next: async () => "/console/ask",
    nextLabel: "Ask a question",
  },
  {
    on: /^\/console\/ask$/,
    target: "ask",
    title: "Ask in plain words",
    body: "Questions are answered from the collected data, with a link for every fact and a chart when numbers are involved. The demo answers a fixed set of questions; a real model takes any.",
    task: "Click one of the questions.",
    nextLabel: "Finish",
  },
];

const TourContext = createContext<{ start: () => void; active: boolean }>({ start: () => {}, active: false });
export const useTour = () => useContext(TourContext);

function load(): Saved {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return { step: -1, seen: false, ...JSON.parse(raw) };
  } catch {
    // Private windows can refuse storage; the tour then simply starts fresh each visit.
  }
  return { step: -1, seen: false };
}

export function TourProvider({ children, autoStart }: { children: ReactNode; autoStart: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const [saved, setSaved] = useState<Saved | null>(null);
  const [welcome, setWelcome] = useState(false);
  const [finished, setFinished] = useState(false);

  useEffect(() => setSaved(load()), []);
  const update = useCallback((patch: Partial<Saved>) => {
    setSaved((cur) => {
      const next = { ...(cur ?? { step: -1, seen: false }), ...patch };
      try {
        window.localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        // see load()
      }
      return next;
    });
  }, []);

  // First visit to the public demo: offer the tour once.
  useEffect(() => {
    if (autoStart && saved && !saved.seen && saved.step < 0) setWelcome(true);
  }, [autoStart, saved]);

  const index = saved?.step ?? -1;
  const step = index >= 0 ? STEPS[index] : undefined;

  const start = useCallback(() => {
    setWelcome(false);
    setFinished(false);
    update({ step: 0, seen: true, deployment: undefined, incident: undefined });
    router.push("/console");
  }, [router, update]);
  const stop = useCallback(() => update({ step: -1, seen: true }), [update]);

  const goNext = useCallback(async () => {
    if (!saved || !step) return;
    if (step.act) return step.act();
    if (index === STEPS.length - 1) {
      update({ step: -1 });
      setFinished(true);
      return;
    }
    const following = STEPS[index + 1];
    update({ step: index + 1 });
    if (!following.on.test(pathname)) router.push(step.next ? await step.next(saved) : "/console");
  }, [saved, step, index, pathname, router, update]);

  // Doing the step for real moves the tour on by itself.
  useEffect(() => {
    if (!step || index === STEPS.length - 1) return;
    const following = STEPS[index + 1];
    if (!step.on.test(pathname) && following.on.test(pathname)) update({ step: index + 1 });
  }, [pathname, step, index, update]);
  useEffect(() => {
    const onBroke = (e: Event) => {
      const detail = (e as CustomEvent<{ deployment_id: string; incident_id: string }>).detail;
      setSaved((cur) => {
        if (!cur || cur.step < 0) return cur;
        const at = STEPS[cur.step].target === "break" ? cur.step + 1 : cur.step;
        const next = { ...cur, step: at, deployment: detail.deployment_id, incident: detail.incident_id };
        try {
          window.localStorage.setItem(KEY, JSON.stringify(next));
        } catch {
          // see load()
        }
        return next;
      });
    };
    window.addEventListener(BROKE_EVENT, onBroke);
    return () => window.removeEventListener(BROKE_EVENT, onBroke);
  }, []);

  const value = useMemo(() => ({ start, active: index >= 0 }), [start, index]);
  const onPage = !!step && step.on.test(pathname);

  return (
    <TourContext.Provider value={value}>
      {children}
      {step && onPage && <Pointer key={index} step={step} index={index} onNext={goNext} onBack={index > 0 && STEPS[index - 1].on.test(pathname) ? () => update({ step: index - 1 }) : undefined} onStop={stop} />}
      {step && !onPage && saved && <Resume step={step} index={index} onStop={stop} onGo={async () => router.push(index > 0 && STEPS[index - 1].next ? await STEPS[index - 1].next!(saved) : "/console")} />}
      <AnimatePresence>
        {welcome && (
          <Card
            key="welcome"
            title="Welcome to the Opscend demo"
            onClose={() => {
              setWelcome(false);
              update({ seen: true });
            }}
            actions={
              <>
                <button
                  onClick={() => {
                    setWelcome(false);
                    update({ seen: true });
                  }}
                  className="text-[13px] text-muted hover:text-fg"
                >
                  Look around on my own
                </button>
                <button onClick={start} className="group inline-flex h-9 items-center gap-2 rounded-lg bg-fg px-4 text-[13px] font-medium text-bg hover:opacity-85">
                  Take the 2-minute tour <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
                </button>
              </>
            }
          >
            <p>
              You are in a live console with sample data. Break a deploy, watch the incident open and read the investigator&apos;s report. Nothing here touches a real provider, and the AI answers are scripted.
            </p>
          </Card>
        )}
        {finished && (
          <Card
            key="finished"
            title="That is the whole loop"
            onClose={() => setFinished(false)}
            actions={
              <>
                <button onClick={() => setFinished(false)} className="text-[13px] text-muted hover:text-fg">
                  Keep exploring
                </button>
                <Link href={DOCS_URL} className="group inline-flex h-9 items-center gap-2 rounded-lg bg-fg px-4 text-[13px] font-medium text-bg hover:opacity-85">
                  Setup guide <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
                </Link>
              </>
            }
          >
            <p>A deploy broke, an incident opened, and the cause was waiting with its evidence. To try it on your own deploys, with a real model, run it on your machine:</p>
            <QuickstartCommands className="mt-3" />
          </Card>
        )}
      </AnimatePresence>
    </TourContext.Provider>
  );
}

function Card({ title, children, actions, onClose }: { title: string; children: ReactNode; actions: ReactNode; onClose: () => void }) {
  return (
    <motion.div className="fixed inset-0 z-[85] grid grid-cols-1 place-items-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <motion.div role="dialog" aria-modal aria-label={title} initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }} transition={{ duration: 0.22 }} className="panel w-full max-w-[460px] bg-surface p-5 shadow-[0_30px_100px_rgb(0_0_0/0.9)]">
        <div className="flex items-start gap-3">
          <Sherlog size={48} />
          <div className="min-w-0 flex-1 pt-1 text-[16px] font-medium">{title}</div>
          <button onClick={onClose} className="text-faint hover:text-fg" aria-label="Close">
            <X size={15} />
          </button>
        </div>
        <div className="mt-3 text-[13px] leading-relaxed text-muted">{children}</div>
        <div className="mt-5 flex flex-wrap items-center justify-end gap-x-5 gap-y-2">{actions}</div>
      </motion.div>
    </motion.div>
  );
}

/** Shown when the visitor wandered off mid-tour. */
function Resume({ step, index, onGo, onStop }: { step: Step; index: number; onGo: () => void; onStop: () => void }) {
  return (
    <div className="fixed inset-x-3 bottom-3 z-[60] mx-auto flex max-w-[420px] items-center gap-3 rounded-xl border border-[var(--line-strong)] bg-surface px-4 py-3 shadow-[0_20px_60px_rgb(0_0_0/0.7)] sm:left-auto sm:right-4 sm:mx-0">
      <div className="min-w-0 flex-1">
        <div className="label-mono text-faint">
          Tour paused · {index + 1} of {STEPS.length}
        </div>
        <div className="truncate text-[13px]">{step.title}</div>
      </div>
      <button onClick={onStop} className="text-[12.5px] text-muted hover:text-fg">
        End
      </button>
      <button onClick={onGo} className="h-8 rounded-lg bg-fg px-3 text-[12.5px] font-medium text-bg hover:opacity-85">
        Resume
      </button>
    </div>
  );
}

const PAD = 6;

function Pointer({ step, index, onNext, onBack, onStop }: { step: Step; index: number; onNext: () => void; onBack?: () => void; onStop: () => void }) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [busy, setBusy] = useState(false);
  const card = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const scrolled = useRef(false);

  // The page loads its data after the step appears, so keep looking for the target.
  useEffect(() => {
    if (!step.target) return;
    const find = () => {
      const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
      if (!el) return setRect(null);
      if (!scrolled.current) {
        scrolled.current = true;
        // Something taller than the screen is shown from its top, not its middle.
        el.style.scrollMarginTop = "12px";
        const tall = el.getBoundingClientRect().height > window.innerHeight * 0.7;
        // On a phone the card is docked at the bottom, so the target goes to the top.
        el.scrollIntoView({ block: tall || window.innerWidth < 640 ? "start" : "center", behavior: "smooth" });
      }
      const r = el.getBoundingClientRect();
      setRect((cur) => (cur && cur.top === r.top && cur.left === r.left && cur.width === r.width && cur.height === r.height ? cur : r));
    };
    find();
    const timer = window.setInterval(find, 250);
    window.addEventListener("resize", find);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", find);
    };
  }, [step.target]);

  // Beside the target on a wide screen; docked to the bottom on a phone.
  useLayoutEffect(() => {
    const el = card.current;
    if (!el || !rect || window.innerWidth < 640) return setPlace(null);
    const { width, height } = el.getBoundingClientRect();
    if (rect.height > window.innerHeight * 0.7) {
      // No room above or below a tall target: sit beside it, or over its lower corner.
      const beside = rect.left - width - 16 > 12 ? rect.left - width - 16 : rect.right + 16 + width < window.innerWidth ? rect.right + 16 : null;
      return setPlace(beside === null ? { top: window.innerHeight - height - 16, left: window.innerWidth - width - 16 } : { top: Math.max(96, Math.min(rect.top, window.innerHeight - height - 16)), left: beside });
    }
    const below = rect.bottom + PAD + 12;
    const above = rect.top - PAD - 12 - height;
    const top = below + height < window.innerHeight - 8 ? below : above > 8 ? above : window.innerHeight - height - 12;
    const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
    setPlace({ top, left });
  }, [rect]);

  const last = index === STEPS.length - 1;
  return (
    <>
      {rect && (
        <div
          aria-hidden
          className="pointer-events-none fixed z-[55] rounded-xl border border-[var(--signal)] transition-all duration-300"
          style={{ top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2, boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.42), 0 0 0 4px color-mix(in oklab, var(--signal) 22%, transparent)" }}
        />
      )}
      <motion.div
        ref={card}
        role="dialog"
        aria-label={`Tour step ${index + 1} of ${STEPS.length}: ${step.title}`}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.22 }}
        className="fixed inset-x-3 bottom-3 z-[60] rounded-xl border border-[var(--line-strong)] bg-surface p-4 shadow-[0_20px_60px_rgb(0_0_0/0.75)] sm:inset-x-auto sm:bottom-auto sm:w-[360px]"
        style={place ? { top: place.top, left: place.left } : window.innerWidth >= 640 ? { bottom: 16, right: 16 } : undefined}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="label-mono text-faint">
            Tour · {index + 1} of {STEPS.length}
          </span>
          <button onClick={onStop} className="-mr-1 grid size-6 place-items-center text-faint hover:text-fg" aria-label="End the tour">
            <X size={14} />
          </button>
        </div>
        <div className="mt-1.5 text-[14.5px] font-medium">{step.title}</div>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">{step.body}</p>
        {step.task && (
          <p className="mt-2.5 flex items-start gap-2 text-[12.5px] leading-relaxed text-fg">
            <span className="mt-[7px] size-1.5 shrink-0 bg-[var(--signal)]" />
            {step.task}
          </p>
        )}
        <div className="mt-3.5 flex items-center gap-3">
          <div className="flex flex-1 gap-1" aria-hidden>
            {STEPS.map((_, i) => (
              <span key={i} className={`h-0.5 flex-1 ${i <= index ? "bg-[var(--signal)]" : "bg-line"}`} />
            ))}
          </div>
          {onBack && (
            <button onClick={onBack} className="text-[12.5px] text-muted hover:text-fg">
              Back
            </button>
          )}
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onNext();
              } finally {
                setBusy(false);
              }
            }}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-fg px-3 text-[12.5px] font-medium text-bg hover:opacity-85 disabled:opacity-60"
          >
            {step.nextLabel ?? (last ? "Finish" : "Next")} <ArrowRight size={13} />
          </button>
        </div>
      </motion.div>
    </>
  );
}
