"use client";

import { AnimatePresence, motion } from "motion/react";
import { CircleAlert, CircleCheck, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface Toast {
  id: number;
  tone: "ok" | "error";
  title: string;
  detail?: string;
}

const Ctx = createContext<{ ok: (title: string, detail?: string) => void; error: (title: string, detail?: string) => void } | null>(null);

export function useToast() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (tone: Toast["tone"], title: string, detail?: string) => {
      const id = ++seq;
      setToasts((t) => [...t.slice(-3), { id, tone, title, detail }]);
      setTimeout(() => dismiss(id), tone === "error" ? 7000 : 3500);
    },
    [dismiss],
  );
  const value = useMemo(
    () => ({ ok: (t: string, d?: string) => push("ok", t, d), error: (t: string, d?: string) => push("error", t, d) }),
    [push],
  );

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2" role="status" aria-live="polite">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24 }}
              transition={{ duration: 0.22 }}
              className="pointer-events-auto flex items-start gap-3 rounded-xl border border-line bg-raised p-3 shadow-[0_16px_50px_rgb(0_0_0/0.7)]"
            >
              {t.tone === "ok" ? <CircleCheck size={15} className="mt-0.5 shrink-0 text-ok" /> : <CircleAlert size={15} className="mt-0.5 shrink-0 text-err" />}
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{t.title}</div>
                {t.detail && <div className="mt-0.5 break-words text-[12px] leading-relaxed text-muted">{t.detail}</div>}
              </div>
              <button onClick={() => dismiss(t.id)} className="text-faint hover:text-fg" aria-label="Dismiss">
                <X size={13} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}
