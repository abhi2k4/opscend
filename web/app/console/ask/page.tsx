"use client";

import { ArrowUp, MessageSquarePlus, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { mutate } from "swr";
import { MessageView, Suggestions } from "@/components/console/ask";
import { useNow } from "@/components/console/deploys";
import { useToast } from "@/components/console/toast";
import { Button, Kbd, Skeleton, Spinner } from "@/components/ui/primitives";
import { Sherlog } from "@/components/ui/sherlog";
import { api, useApi, type ApiError } from "@/lib/api";
import { cn, compact, timeAgo } from "@/lib/format";
import type { ChatSession, ChatSessionSummary, SystemInfo } from "@/lib/types";

const isBusy = (chat?: ChatSession) => !!chat?.messages.some((m) => m.status === "pending" || m.status === "running");

export default function AskPage() {
  return (
    <Suspense>
      <Ask />
    </Suspense>
  );
}

function Ask() {
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const now = useNow();
  const chatId = params.get("c");
  const initial = params.get("q");

  const system = useApi<SystemInfo>("/system", { revalidateOnFocus: false });
  const sessions = useApi<ChatSessionSummary[]>("/chat/sessions");
  const chat = useApi<ChatSession>(chatId ? `/chat/sessions/${chatId}` : null, {
    refreshInterval: (cur) => (isBusy(cur) ? 1000 : 0),
  });
  const busy = isBusy(chat.data);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  // Refresh the sidebar when an answer lands (its updated_at moves).
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) sessions.mutate();
    wasBusy.current = busy;
  }, [busy, sessions]);

  const messageCount = chat.data?.messages.length ?? 0;
  const lastSteps = chat.data?.messages.at(-1)?.steps.length ?? 0;
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messageCount, lastSteps, busy]);

  useEffect(() => {
    input.current?.focus();
  }, [chatId]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || sending || busy) return;
    setSending(true);
    try {
      if (chatId) {
        const next = await api<ChatSession>(`/chat/sessions/${chatId}/messages`, { method: "POST", json: { content: question } });
        await chat.mutate(next, { revalidate: false });
      } else {
        const created = await api<ChatSession>("/chat/sessions", { method: "POST", json: { content: question } });
        await mutate(`/chat/sessions/${created.id}`, created, { revalidate: false });
        router.replace(`/console/ask?c=${created.id}`);
      }
      setDraft("");
      sessions.mutate();
    } catch (e) {
      const err = e as ApiError;
      toast.error(err.status === 409 ? "Can't ask right now" : "Could not send the question", err.message);
    } finally {
      setSending(false);
    }
  };

  // ⌘K → "Ask Opscend" lands here with ?q=; ask it once, then drop it from the URL.
  const askedInitial = useRef<string | null>(null);
  useEffect(() => {
    if (!initial || chatId || askedInitial.current === initial) return;
    askedInitial.current = initial;
    send(initial);
  }, [initial, chatId]);

  const remove = async (id: string) => {
    try {
      await api(`/chat/sessions/${id}`, { method: "DELETE" });
      sessions.mutate((list) => list?.filter((s) => s.id !== id), { revalidate: true });
      if (id === chatId) router.replace("/console/ask");
    } catch (e) {
      toast.error("Could not delete the conversation", (e as ApiError).message);
    }
  };

  const configured = system.data?.ai.configured ?? true;

  return (
    <div className="-m-4 flex h-[calc(100dvh-3rem)] border-line sm:-m-6 min-[1320px]:border-x">
      {/* conversations */}
      <aside className="hidden w-[248px] shrink-0 flex-col border-r border-line md:flex">
        <div className="flex h-11 items-center justify-between border-b border-line px-3">
          <span className="label-mono">Conversations</span>
          <button onClick={() => router.replace("/console/ask")} className="grid size-7 place-items-center rounded-md text-muted hover:bg-raised hover:text-fg" title="New conversation" aria-label="New conversation">
            <MessageSquarePlus size={14} />
          </button>
        </div>
        <ul className="flex-1 space-y-px overflow-y-auto p-1.5">
          {!sessions.data && [0, 1, 2].map((i) => <Skeleton key={i} className="m-1 h-9" />)}
          {sessions.data?.length === 0 && <li className="px-2.5 py-6 text-center text-[12px] text-faint">No conversations yet.</li>}
          {sessions.data?.map((s) => (
            <li key={s.id} className="group relative">
              <button
                onClick={() => router.replace(`/console/ask?c=${s.id}`)}
                className={cn("block w-full rounded-md px-2.5 py-2 pr-8 text-left transition-colors", s.id === chatId ? "bg-raised text-fg" : "text-muted hover:bg-raised/60 hover:text-fg")}
              >
                <div className="truncate text-[12.5px]">{s.title}</div>
                <div className="font-mono text-[10.5px] text-faint">{timeAgo(s.updated_at, now)}</div>
              </button>
              <button
                onClick={() => remove(s.id)}
                className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-faint opacity-0 hover:bg-bg hover:text-err focus:opacity-100 group-hover:opacity-100"
                title="Delete conversation"
                aria-label={`Delete conversation ${s.title}`}
              >
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* thread */}
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-3 border-b border-line px-4">
          <h1 className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{chatId ? (chat.data?.title ?? "…") : "Ask Opscend"}</h1>
          {chat.data && <span className="font-mono text-[11px] text-faint">{compact(chat.data.tokens_used)} tok</span>}
          {chatId && (
            <Button size="sm" variant="ghost" className="md:hidden" onClick={() => router.replace("/console/ask")}>
              <MessageSquarePlus size={13} /> New
            </Button>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {!chatId && !sending && (
            <Suggestions onPick={send} demo={system.data?.demo_mode}>
              <Sherlog size={56} animated={false} />
              <h2 className="mt-3 text-[17px] font-medium tracking-tight">Ask about your deploys</h2>
              <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-muted">
                Questions are answered from what Opscend has collected from Vercel, Railway and GitHub, with every fact linked to the deploy, log line or commit it came from. Read-only: nothing gets changed.
              </p>
            </Suggestions>
          )}
          {!chatId && sending && (
            <div className="grid h-full place-items-center text-muted">
              <Spinner className="size-4" />
            </div>
          )}
          {chatId && chat.error && !chat.data && <div className="p-8 text-center text-[13px] text-muted">{chat.error.status === 404 ? "This conversation no longer exists." : chat.error.message}</div>}
          {chatId && !chat.data && !chat.error && (
            <div className="mx-auto max-w-3xl space-y-4 p-6">
              <Skeleton className="ml-auto h-10 w-1/2" />
              <Skeleton className="h-24" />
            </div>
          )}
          {chat.data && (
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
              {chat.data.messages.map((m) => (
                <MessageView key={m.id} message={m} />
              ))}
              <div ref={bottom} />
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-line p-3">
          {system.data?.ai.simulated && (
            <p className="mx-auto mb-2 max-w-3xl text-[12px] text-muted">
              <span className="text-warn">Simulated answers.</span> This demo replies from a script to a fixed set of questions about the sample data. On your own install a real model answers anything.
            </p>
          )}
          {!configured && (
            <p className="mx-auto mb-2 max-w-3xl text-[12px] text-warn">
              No AI model is configured. Set <code className="font-mono">GROQ_API_KEY</code> in .env and restart the API.
            </p>
          )}
          <form
            className="mx-auto flex max-w-3xl items-end gap-2 rounded-lg border border-line bg-surface p-2 focus-within:border-[var(--line-strong)]"
            onSubmit={(e) => {
              e.preventDefault();
              send(draft);
            }}
          >
            <textarea
              ref={input}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(draft);
                }
              }}
              rows={1}
              maxLength={4000}
              placeholder={busy ? "Answering…" : chatId ? "Ask a follow-up…" : "Ask about deploys, logs, incidents or commits…"}
              className="max-h-40 min-h-8 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[13.5px] leading-[1.5] outline-none [field-sizing:content] placeholder:text-faint"
              aria-label="Your question"
            />
            <Button type="submit" variant="primary" size="sm" className="size-8 p-0" disabled={!draft.trim() || busy || !configured} loading={sending} aria-label="Send">
              {!sending && <ArrowUp size={14} />}
            </Button>
          </form>
          <div className="mx-auto mt-1.5 flex max-w-3xl items-center gap-1 font-mono text-[10.5px] text-faint">
            <Kbd>↵</Kbd> send <span className="mx-1">·</span> <Kbd>⇧</Kbd>
            <Kbd>↵</Kbd> new line
          </div>
        </div>
      </section>
    </div>
  );
}
