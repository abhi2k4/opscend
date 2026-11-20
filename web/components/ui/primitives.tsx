"use client";

import { Check, Copy } from "lucide-react";
import Link from "next/link";
import { useCallback, useRef, useState, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/format";
import type { Confidence, DeployStatus, HealthState, LogLevel } from "@/lib/types";

// ───────────────────────────── buttons

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
const buttonBase =
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-[background,border-color,color,transform,opacity] duration-150 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none select-none";
const buttonVariants: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-ink hover:opacity-85",
  secondary: "border border-line bg-raised text-fg hover:border-[var(--line-strong)] hover:bg-[var(--raised-hover)]",
  ghost: "text-muted hover:text-fg hover:bg-raised",
  danger: "border border-err/40 bg-err/10 text-err hover:bg-err/20",
};
const buttonSizes = { sm: "h-7 px-2.5 text-[12px]", md: "h-8 px-3 text-[13px]", lg: "h-10 px-4 text-[14px]" };

interface ButtonOwnProps {
  variant?: ButtonVariant;
  size?: keyof typeof buttonSizes;
  loading?: boolean;
}

export function Button({ variant = "secondary", size = "md", loading, className, children, ...props }: ButtonOwnProps & ComponentProps<"button">) {
  return (
    <button className={cn(buttonBase, buttonVariants[variant], buttonSizes[size], className)} disabled={loading || props.disabled} {...props}>
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function ButtonLink({ variant = "secondary", size = "md", className, ...props }: ButtonOwnProps & ComponentProps<typeof Link>) {
  return <Link className={cn(buttonBase, buttonVariants[variant], buttonSizes[size], className)} {...props} />;
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn("inline-block size-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent", className)}
      aria-label="Loading"
    />
  );
}

// ───────────────────────────── badges

const STATUS: Record<DeployStatus, { label: string; color: string }> = {
  ready: { label: "Ready", color: "var(--ok)" },
  failed: { label: "Failed", color: "var(--err)" },
  building: { label: "Building", color: "var(--warn)" },
  queued: { label: "Queued", color: "var(--muted)" },
  canceled: { label: "Canceled", color: "var(--faint)" },
};

export const statusColor = (s: DeployStatus) => STATUS[s]?.color ?? "var(--muted)";

export function Dot({ color, pulse, className }: { color: string; pulse?: boolean; className?: string }) {
  return (
    <span className={cn("relative inline-flex size-2 shrink-0", className)}>
      {pulse && <span className="absolute inset-0 animate-pulse-ring rounded-full" style={{ background: color }} />}
      <span className="relative size-2 rounded-full" style={{ background: color }} />
    </span>
  );
}

export function Tag({ color = "var(--muted)", children, className }: { color?: string; children: ReactNode; className?: string }) {
  return (
    <span
      className={cn("inline-flex h-5 items-center gap-1.5 rounded-sm border px-1.5 font-mono text-[10.5px] uppercase tracking-wider", className)}
      style={{ color, borderColor: `color-mix(in oklab, ${color} 30%, transparent)`, background: `color-mix(in oklab, ${color} 9%, transparent)` }}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: DeployStatus }) {
  const s = STATUS[status] ?? { label: status, color: "var(--muted)" };
  return (
    <Tag color={s.color}>
      <Dot color={s.color} pulse={status === "building"} className="scale-75" />
      {s.label}
    </Tag>
  );
}

const LEVEL: Record<LogLevel, string> = { debug: "var(--faint)", info: "var(--info)", warn: "var(--warn)", error: "var(--err)" };
export const levelColor = (l: LogLevel) => LEVEL[l] ?? "var(--muted)";

export function LevelBadge({ level }: { level: LogLevel }) {
  return (
    <span
      className="inline-block w-[42px] shrink-0 rounded-sm py-px text-center font-mono text-[10px] uppercase tracking-wider"
      style={{ color: levelColor(level), background: `color-mix(in oklab, ${levelColor(level)} 12%, transparent)` }}
    >
      {level}
    </span>
  );
}

export function HealthBadge({ health }: { health: HealthState }) {
  const color = health === "up" ? "var(--ok)" : health === "down" ? "var(--err)" : "var(--faint)";
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider" style={{ color }}>
      <Dot color={color} pulse={health === "down"} />
      {health}
    </span>
  );
}

export function ConfidenceMeter({ confidence }: { confidence: Confidence }) {
  const n = { low: 1, medium: 2, high: 3 }[confidence];
  const color = { low: "var(--err)", medium: "var(--warn)", high: "var(--ok)" }[confidence];
  return (
    <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider" style={{ color }}>
      <span className="flex gap-0.5">
        {[1, 2, 3].map((i) => (
          <span key={i} className="h-3 w-1.5 rounded-[1px]" style={{ background: i <= n ? color : "var(--line)" }} />
        ))}
      </span>
      {confidence}
    </span>
  );
}

// ───────────────────────────── bits

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn("inline-grid h-[18px] min-w-[18px] place-items-center rounded-sm border border-line bg-raised px-1 font-mono text-[10px] text-muted", className)}>
      {children}
    </kbd>
  );
}

export function useCopy() {
  const [copied, setCopied] = useState(false);
  const t = useRef<ReturnType<typeof setTimeout>>(undefined);
  const copy = useCallback((text: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      clearTimeout(t.current);
      t.current = setTimeout(() => setCopied(false), 1400);
    });
  }, []);
  return { copied, copy };
}

export function CopyButton({ value, className, label }: { value: string; className?: string; label?: string }) {
  const { copied, copy } = useCopy();
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        copy(value);
      }}
      title={label ?? "Copy"}
      aria-label={label ?? "Copy"}
      className={cn("inline-grid size-6 place-items-center rounded-md text-faint transition-colors hover:bg-raised hover:text-fg", className)}
    >
      {copied ? <Check size={12} className="text-accent" /> : <Copy size={12} />}
    </button>
  );
}

/** Monospace value that copies on click. Use for ids, SHAs and URLs. */
export function Mono({ value, display, className }: { value: string; display?: string; className?: string }) {
  const { copied, copy } = useCopy();
  return (
    <button
      type="button"
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        copy(value);
      }}
      title={copied ? "Copied" : `Copy ${value}`}
      className={cn("rounded-sm font-mono text-[12px] text-muted transition-colors hover:text-fg", copied && "text-accent hover:text-accent", className)}
    >
      {copied ? "copied" : (display ?? value)}
    </button>
  );
}

/** Wrapper that feeds the cursor position to the .spotlight CSS effect. */
export function Spotlight({ className, children, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn("spotlight", className)}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
        e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
      }}
      {...props}
    >
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton h-4", className)} />;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="grid size-10 place-items-center rounded-lg border border-line bg-raised text-muted">{icon}</div>}
      <div className="text-[14px] font-medium">{title}</div>
      {children && <p className="max-w-sm text-[13px] leading-relaxed text-muted">{children}</p>}
      {action}
    </div>
  );
}

export function Panel({ className, children, ...props }: ComponentProps<"section">) {
  return (
    <section className={cn("panel overflow-hidden", className)} {...props}>
      {children}
    </section>
  );
}

export function PanelHeader({ title, right, className }: { title: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <header className={cn("flex h-10 items-center justify-between gap-3 border-b border-line px-4", className)}>
      <h2 className="label-mono">{title}</h2>
      {right}
    </header>
  );
}
