"use client";

import { Search, WrapText } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Empty, levelColor, Skeleton } from "@/components/ui/primitives";
import { useApi } from "@/lib/api";
import { clock, cn } from "@/lib/format";
import { highlight } from "@/lib/highlight";
import type { CommitDiff, LogKind, LogLevel, LogLine } from "@/lib/types";

const LEVELS: LogLevel[] = ["error", "warn", "info", "debug"];

/**
 * Log viewer with level filters and search. `focusId` scrolls to and
 * highlights one line — that is how evidence links from a report land here.
 */
export function LogViewer({ deploymentId, kind, focusId }: { deploymentId: string; kind: LogKind; focusId?: string | null }) {
  const { data, error } = useApi<LogLine[]>(`/deployments/${deploymentId}/logs?kind=${kind}`);
  const [off, setOff] = useState<Set<LogLevel>>(new Set());
  const [q, setQ] = useState("");
  const [wrap, setWrap] = useState(false);
  const focusRef = useRef<HTMLDivElement>(null);

  const counts = useMemo(() => {
    const c: Record<LogLevel, number> = { error: 0, warn: 0, info: 0, debug: 0 };
    for (const l of data ?? []) c[l.level] = (c[l.level] ?? 0) + 1;
    return c;
  }, [data]);

  const lines = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((l) => (l.id === focusId || !off.has(l.level)) && (!needle || l.message.toLowerCase().includes(needle)));
  }, [data, off, q, focusId]);

  useEffect(() => {
    if (data && focusId) focusRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [data, focusId]);

  if (error) return <Empty title="Could not load logs">{error.message}</Empty>;
  if (!data) {
    return (
      <div className="space-y-2 p-4">
        {[80, 60, 72, 45, 66, 52].map((w, i) => (
          <Skeleton key={i} className="h-3.5" />
        ))}
      </div>
    );
  }
  if (data.length === 0) return <Empty title={`No ${kind} logs for this deploy`}>The provider returned no lines. They may have expired or the deploy never reached this stage.</Empty>;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        {LEVELS.map((lvl) => {
          const on = !off.has(lvl);
          return (
            <button
              key={lvl}
              aria-pressed={on}
              onClick={() =>
                setOff((s) => {
                  const n = new Set(s);
                  if (n.has(lvl)) n.delete(lvl);
                  else n.add(lvl);
                  return n;
                })
              }
              className={cn("flex h-6 items-center gap-1.5 rounded-sm border px-2 font-mono text-[10.5px] uppercase tracking-wider transition-opacity", !on && "opacity-35")}
              style={{ color: levelColor(lvl), borderColor: `color-mix(in oklab, ${levelColor(lvl)} 30%, transparent)`, background: `color-mix(in oklab, ${levelColor(lvl)} 8%, transparent)` }}
            >
              {lvl} <span className="tabular-nums opacity-70">{counts[lvl]}</span>
            </button>
          );
        })}
        <label className="ml-auto flex h-7 w-full items-center gap-2 rounded-md border border-line bg-bg px-2 sm:w-56">
          <Search size={12} className="text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter lines" className="w-full bg-transparent font-mono text-[11.5px] outline-none placeholder:text-faint" />
        </label>
        <button onClick={() => setWrap((w) => !w)} aria-pressed={wrap} title="Wrap lines" className={cn("grid size-7 place-items-center rounded-md border border-line", wrap ? "bg-raised text-fg" : "text-faint hover:text-fg")}>
          <WrapText size={13} />
        </button>
      </div>
      <div className="max-h-[560px] overflow-auto bg-bg/50 py-1.5 font-mono text-[12px] leading-[1.7]" role="log">
        {lines.map((l, i) => {
          const focused = l.id === focusId;
          return (
            <div
              key={l.id}
              id={l.id}
              ref={focused ? focusRef : undefined}
              className={cn(
                "group flex gap-3 px-3",
                !wrap && "w-max min-w-full",
                l.level === "error" && "bg-err/[0.06]",
                focused && "bg-accent/10 outline outline-1 -outline-offset-1 outline-accent/60",
              )}
            >
              <span className="w-8 shrink-0 select-none text-right text-faint">{i + 1}</span>
              <span className="shrink-0 select-none text-faint">{clock(l.ts)}</span>
              <span className="w-10 shrink-0 select-none uppercase" style={{ color: levelColor(l.level) }}>
                {l.level}
              </span>
              <span className={cn(wrap ? "whitespace-pre-wrap break-all" : "whitespace-pre", l.level === "error" ? "text-fg" : l.level === "debug" ? "text-faint" : "text-fg/75")}>{l.message}</span>
              <span className="ml-auto shrink-0 select-none pl-4 text-faint opacity-0 group-hover:opacity-100">{l.id}</span>
            </div>
          );
        })}
        {lines.length === 0 && <div className="px-4 py-8 text-center text-muted">No lines match.</div>}
      </div>
    </div>
  );
}

const langOf = (file: string) => (file.endsWith(".py") ? "python" : /\.(ts|tsx|js|jsx)$/.test(file) ? "ts" : file.endsWith(".json") ? "json" : "plain");

export function DiffView({ deploymentId }: { deploymentId: string }) {
  const { data, error } = useApi<CommitDiff>(`/deployments/${deploymentId}/diff`);
  if (error) return <Empty title="No diff available">{error.status === 404 ? "Connect GitHub so Opscend can fetch the commit for this deploy." : error.message}</Empty>;
  if (!data) return <div className="p-4"><Skeleton className="h-40" /></div>;

  return (
    <div className="space-y-3 p-3">
      {data.files.map((f) => (
        <div key={f.filename} className="overflow-hidden rounded-lg border border-line">
          <div className="flex items-center gap-3 border-b border-line bg-raised/50 px-3 py-2 font-mono text-[11.5px]">
            <span className="truncate text-fg">{f.filename}</span>
            <span className="text-faint">{f.status}</span>
            <span className="ml-auto text-ok">+{f.additions}</span>
            <span className="text-err">−{f.deletions}</span>
          </div>
          {f.patch ? (
            <div className="overflow-x-auto bg-bg/50 py-1 font-mono text-[12px] leading-[1.7]">
              {f.patch.split("\n").map((line, i) => {
                const kind = line.startsWith("@@") ? "hunk" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "ctx";
                return (
                  <div
                    key={i}
                    className={cn(
                      "flex w-max min-w-full px-3",
                      kind === "add" && "bg-ok/[0.09]",
                      kind === "del" && "bg-err/[0.09]",
                      kind === "hunk" && "bg-info/[0.07] text-info",
                    )}
                  >
                    <span className={cn("w-4 shrink-0 select-none", kind === "add" ? "text-ok" : kind === "del" ? "text-err" : "text-faint")}>{kind === "hunk" ? "" : line[0] === " " ? "" : line[0]}</span>
                    {kind === "hunk" ? (
                      <span className="whitespace-pre">{line}</span>
                    ) : (
                      <span className="whitespace-pre text-fg/85" dangerouslySetInnerHTML={{ __html: highlight(line.slice(1), langOf(f.filename)) || "&nbsp;" }} />
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="px-3 py-4 text-[12.5px] text-muted">Binary file or patch too large to display.</div>
          )}
        </div>
      ))}
      {data.files.length === 0 && <Empty title="This commit changed no files" />}
    </div>
  );
}
