"use client";

import { ArrowRight } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button } from "@/components/ui/primitives";
import { Wordmark } from "@/components/ui/provider";
import { Sherlog } from "@/components/ui/sherlog";
import { api, ApiError, useApi } from "@/lib/api";
import type { SystemInfo, User } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The public demo has no login: everyone is already in.
  const system = useApi<SystemInfo>("/system", { revalidateOnFocus: false });
  useEffect(() => {
    if (system.data?.public_demo) router.replace("/console");
  }, [system.data, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<User>("/auth/login", { method: "POST", json: { email, password } });
      const next = params.get("next");
      router.replace(next && next.startsWith("/console") ? next : "/console");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
      setBusy(false);
    }
  };

  const input =
    "h-10 w-full rounded-lg border border-line bg-bg px-3 text-[14px] outline-none transition-colors placeholder:text-faint focus:border-accent/60";

  return (
    <motion.form
      onSubmit={submit}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="panel relative w-full max-w-[380px] p-7"
    >
      <div className="flex items-start justify-between">
        <Link href="/">
          <Wordmark />
        </Link>
        <Sherlog size={64} className="-mr-2 -mt-3" />
      </div>
      <h1 className="mt-6 text-[20px] font-medium tracking-tight">Sign in to the console</h1>
      <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
        Single local user. Credentials are <code className="font-mono text-fg">OPSCEND_ADMIN_EMAIL</code> and{" "}
        <code className="font-mono text-fg">OPSCEND_ADMIN_PASSWORD</code> from your <code className="font-mono text-fg">.env</code>.
      </p>
      <div className="mt-6 space-y-3">
        <label className="block">
          <span className="label-mono mb-1.5 block">Email</span>
          <input className={input} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@opscend.local" autoFocus />
        </label>
        <label className="block">
          <span className="label-mono mb-1.5 block">Password</span>
          <input className={input} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
      </div>
      {error && (
        <div role="alert" className="mt-4 rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12.5px] text-err">
          {error}
        </div>
      )}
      <Button type="submit" variant="primary" size="lg" loading={busy} className="mt-5 w-full">
        Sign in <ArrowRight size={14} />
      </Button>
    </motion.form>
  );
}

export default function LoginPage() {
  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
