"use client";

import { ArrowRight, X } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useEffect } from "react";
import { CopyButton } from "@/components/ui/primitives";
import { Sherlog } from "@/components/ui/sherlog";
import { DOCS_URL, REPO_URL } from "@/lib/site";

export const QUICKSTART = [`git clone ${REPO_URL}.git && cd opscend`, "cp .env.example .env", "docker compose up"];

/** The three commands, with one copy button for all of them. */
export function QuickstartCommands({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-lg border border-line bg-bg ${className}`}>
      <div className="flex h-9 items-center justify-between border-b border-line px-3">
        <span className="label-mono text-faint">Terminal</span>
        <CopyButton value={QUICKSTART.join("\n")} label="Copy commands" />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-[1.9] text-fg/85">
        {QUICKSTART.map((line) => (
          <div key={line}>
            <span className="select-none text-faint">$ </span>
            {line}
          </div>
        ))}
      </pre>
    </div>
  );
}

/** Shown wherever the public demo cannot do the real thing: how to run Opscend yourself. */
export function SelfHostDialog({ onClose, reason }: { onClose: () => void; reason?: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <motion.div className="fixed inset-0 z-[90] grid grid-cols-1 place-items-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <motion.div role="dialog" aria-modal aria-label="Run Opscend yourself" initial={{ opacity: 0, y: 16, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 8 }} transition={{ duration: 0.2 }} className="panel w-full max-w-[480px] bg-surface p-5 shadow-[0_30px_100px_rgb(0_0_0/0.9)]">
        <div className="flex items-start gap-3">
          <Sherlog size={44} />
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-medium">Run it on your own deploys</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{reason ?? "This is the public demo: sample data, and nothing here is connected to a real provider."}</p>
          </div>
          <button type="button" onClick={onClose} className="text-faint hover:text-fg" aria-label="Close">
            <X size={15} />
          </button>
        </div>

        <QuickstartCommands className="mt-4" />
        <ul className="mt-4 space-y-1.5 text-[12.5px] leading-relaxed text-muted">
          <li>Runs on your machine with Docker. No account, nothing leaves it.</li>
          <li>Starts with this same sample data, then you connect Vercel, Railway, GitHub and the rest with read-only tokens.</li>
          <li>Add a free Groq key to <code className="font-mono text-fg">.env</code>, or point it at a model you run yourself (Ollama, LM Studio, vLLM), and the investigator and chat use a real model.</li>
        </ul>

        <div className="mt-5 flex flex-wrap items-center justify-end gap-x-5 gap-y-2">
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="text-[13px] text-muted hover:text-fg">
            View the source
          </a>
          <Link href={DOCS_URL} className="group inline-flex h-9 items-center gap-2 rounded-lg bg-fg px-4 text-[13px] font-medium text-bg transition-opacity hover:opacity-85">
            Setup guide <ArrowRight size={14} className="transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </motion.div>
    </motion.div>
  );
}
