"use client";

import { ArrowUpRight, ChevronRight, FolderClosed, FolderOpen } from "lucide-react";
import { useMemo, useState } from "react";
import { cn } from "@/lib/format";
import type { ChangedFile } from "@/lib/types";

/**
 * Changed files as a folder tree. A file the failure points at is marked in the
 * signal colour, and the guide lines from the root down to it are coloured too, so
 * the eye follows one trail to the suspect. Every file links to the source host.
 */

interface Dir {
  kind: "dir";
  name: string;
  path: string;
  children: Node[];
  files: number;
  additions: number;
  deletions: number;
  hot: boolean;
}
interface Leaf {
  kind: "file";
  name: string;
  path: string;
  file: ChangedFile;
  hot: boolean;
}
type Node = Dir | Leaf;

const MARK = { added: ["A", "text-ok"], modified: ["M", "text-muted"], removed: ["D", "text-err"], renamed: ["R", "text-info"] } as const;
const INDENT = 18;
const OPEN_ALL_UNDER = 40; // larger change sets start with only the suspect's trail open

function build(files: ChangedFile[]): Dir {
  const root: Dir = { kind: "dir", name: "", path: "", children: [], files: 0, additions: 0, deletions: 0, hot: false };
  for (const file of files) {
    const parts = file.filename.split("/");
    let dir = root;
    parts.slice(0, -1).forEach((part, i) => {
      let next = dir.children.find((c): c is Dir => c.kind === "dir" && c.name === part);
      if (!next) {
        next = { kind: "dir", name: part, path: parts.slice(0, i + 1).join("/"), children: [], files: 0, additions: 0, deletions: 0, hot: false };
        dir.children.push(next);
      }
      dir = next;
    });
    dir.children.push({ kind: "file", name: parts[parts.length - 1], path: file.filename, file, hot: file.suspect });
  }
  return tidy(root);
}

/** Totals, folders first, and single-folder chains folded into one row ("apps/api/src"). */
function tidy(dir: Dir): Dir {
  dir.children = dir.children.map((child) => (child.kind === "dir" ? tidy(child) : child));
  dir.children = dir.children.map((child) => {
    if (child.kind === "dir" && child.children.length === 1 && child.children[0].kind === "dir") {
      const only = child.children[0];
      return { ...only, name: `${child.name}/${only.name}` };
    }
    return child;
  });
  dir.children.sort((a, b) => (a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === "dir" ? -1 : 1));
  for (const child of dir.children) {
    dir.files += child.kind === "dir" ? child.files : 1;
    dir.additions += child.kind === "dir" ? child.additions : child.file.additions;
    dir.deletions += child.kind === "dir" ? child.deletions : child.file.deletions;
    dir.hot ||= child.hot;
  }
  return dir;
}

/** Five squares split between added and removed, scaled to the size of the change. */
function ChangeBar({ additions, deletions }: { additions: number; deletions: number }) {
  const total = additions + deletions;
  const filled = total === 0 ? 0 : Math.min(5, Math.max(1, Math.ceil(Math.log2(total + 1))));
  const green = total === 0 ? 0 : Math.round((additions / total) * filled);
  return (
    <span aria-hidden className="hidden gap-px sm:flex">
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={cn("size-1.5", i < green ? "bg-ok" : i < filled ? "bg-err" : "bg-line")} />
      ))}
    </span>
  );
}

function Guides({ trail, hot }: { trail: boolean[]; hot: boolean }) {
  return (
    <span aria-hidden className="flex shrink-0 self-stretch">
      {trail.map((lit, i) => {
        const last = i === trail.length - 1;
        return (
          <span key={i} className="relative" style={{ width: INDENT }}>
            <span className={cn("absolute inset-y-0 left-[7px]", lit ? "w-0.5 bg-[var(--signal)]" : "w-px bg-line")} />
            {last && <span className={cn("absolute left-[7px] top-1/2 w-[9px]", hot ? "h-0.5 bg-[var(--signal)]" : "h-px bg-line")} />}
          </span>
        );
      })}
    </span>
  );
}

function Rows({ nodes, trail, closed, toggle }: { nodes: Node[]; trail: boolean[]; closed: Set<string>; toggle: (path: string) => void }) {
  const lastHot = nodes.reduce((at, node, i) => (node.hot ? i : at), -1);
  return (
    <>
      {nodes.map((node, i) => {
        // The trail runs down this level's guide until it reaches the last suspect branch.
        const mine = [...trail, i <= lastHot];
        const below = [...trail, i < lastHot];
        if (node.kind === "dir") {
          const open = !closed.has(node.path);
          const Icon = open ? FolderOpen : FolderClosed;
          return (
            <li key={node.path} role="treeitem" aria-expanded={open} aria-selected={false}>
              <button type="button" onClick={() => toggle(node.path)} className="flex h-8 w-full items-center gap-2 pr-3 text-left transition-colors hover:bg-raised/60">
                <Guides trail={mine} hot={node.hot} />
                <ChevronRight size={11} className={cn("shrink-0 text-faint transition-transform duration-200", open && "rotate-90")} />
                <Icon size={13} className={cn("shrink-0", node.hot ? "text-[var(--signal)]" : "text-faint")} />
                <span className={cn("min-w-0 flex-1 truncate", node.hot ? "text-fg" : "text-fg/80")}>{node.name}</span>
                <span className="shrink-0 text-faint">{node.files}</span>
                <ChangeBar additions={node.additions} deletions={node.deletions} />
              </button>
              {open && (
                <ul role="group">
                  <Rows nodes={node.children} trail={below} closed={closed} toggle={toggle} />
                </ul>
              )}
            </li>
          );
        }
        const { file } = node;
        const name = (
          <span className={cn("truncate", file.suspect ? "font-medium text-fg" : "text-fg/85", file.status === "removed" && "line-through decoration-faint")}>
            {node.name}
            {file.line ? <span className="text-[var(--signal)]">:{file.line}</span> : null}
          </span>
        );
        return (
          <li key={node.path} role="treeitem" aria-selected={false} className={cn("flex min-h-8 items-center gap-2 pr-3", file.suspect ? "bg-[color-mix(in_oklab,var(--signal)_9%,transparent)]" : "transition-colors hover:bg-raised/60")}>
            <Guides trail={mine} hot={node.hot} />
            <span className={cn("w-3 shrink-0 text-center", MARK[file.status][1])} title={file.status}>
              {MARK[file.status][0]}
            </span>
            <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-0.5 py-1">
              {file.url ? (
                <a href={file.url} target="_blank" rel="noreferrer" title={`Open ${file.filename} on GitHub`} className="group inline-flex min-w-0 items-center gap-1 hover:underline">
                  {name}
                  <ArrowUpRight size={11} className={cn("shrink-0", file.suspect ? "text-[var(--signal)]" : "text-faint opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100")} />
                </a>
              ) : (
                name
              )}
              {file.suspect && (
                <span className="whitespace-nowrap border border-[var(--signal)]/50 px-1.5 text-[10px] uppercase leading-[18px] tracking-wider text-[var(--signal)]" title={file.suspect_reason ?? undefined}>
                  suspect<span className="max-sm:hidden"> · {file.suspect_reason}</span>
                </span>
              )}
            </span>
            <span className="shrink-0 text-ok">+{file.additions}</span>
            <span className="w-9 shrink-0 text-right text-err">−{file.deletions}</span>
            <ChangeBar additions={file.additions} deletions={file.deletions} />
          </li>
        );
      })}
    </>
  );
}

export function FileTree({ files }: { files: ChangedFile[] }) {
  const root = useMemo(() => build(files), [files]);
  const [closed, setClosed] = useState<Set<string>>(() => {
    // Big change sets open only along the trail to a suspect.
    const start = new Set<string>();
    if (files.length <= OPEN_ALL_UNDER) return start;
    const walk = (dir: Dir) =>
      dir.children.forEach((child) => {
        if (child.kind !== "dir") return;
        if (!child.hot) start.add(child.path);
        walk(child);
      });
    walk(root);
    return start;
  });
  const toggle = (path: string) =>
    setClosed((prev) => {
      const next = new Set(prev);
      if (!next.delete(path)) next.add(path);
      return next;
    });
  const suspects = files.filter((f) => f.suspect);

  return (
    <div>
      {suspects.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-[var(--signal)]/40 bg-[color-mix(in_oklab,var(--signal)_7%,transparent)] px-3 py-2.5 text-[12.5px]">
          <span className="size-2 shrink-0 bg-[var(--signal)]" aria-hidden />
          <span className="text-fg/90">
            {suspects.length === 1 ? "The failure points at one changed file:" : `The failure points at ${suspects.length} changed files:`}
          </span>
          {suspects.map((f) =>
            f.url ? (
              <a key={f.filename} href={f.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-[11.5px] text-fg underline decoration-[var(--signal)] underline-offset-4 hover:text-[var(--signal)]">
                {f.filename}
                {f.line ? `:${f.line}` : ""} <ArrowUpRight size={11} />
              </a>
            ) : (
              <span key={f.filename} className="font-mono text-[11.5px] text-fg">
                {f.filename}
              </span>
            ),
          )}
        </div>
      )}
      <ul role="tree" aria-label="Changed files" className="overflow-hidden rounded-lg border border-line py-1 font-mono text-[11.5px]">
        <Rows nodes={root.children} trail={[]} closed={closed} toggle={toggle} />
      </ul>
    </div>
  );
}
