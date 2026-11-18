"use client";

import { motion } from "motion/react";
import { Bomb, FlaskConical, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { mutate } from "swr";
import { InvestigateButton } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { useToast } from "@/components/console/toast";
import { Button, ButtonLink, Empty, Panel, Skeleton, Spotlight, Tag } from "@/components/ui/primitives";
import { api, ApiError, useApi } from "@/lib/api";
import type { DemoScenario, SystemInfo } from "@/lib/types";

interface Broken {
  deployment_id: string;
  incident_id: string | null;
}

export default function ChaosPage() {
  const system = useApi<SystemInfo>("/system", { revalidateOnFocus: false });
  const scenarios = useApi<DemoScenario[]>(system.data?.demo_mode ? "/demo/scenarios" : null, { revalidateOnFocus: false });
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [broken, setBroken] = useState<Record<string, Broken>>({});

  const refreshAll = () => mutate((key) => typeof key === "string" && !key.startsWith("/system") && !key.startsWith("/auth"));

  const breakIt = async (s: DemoScenario) => {
    setBusy(s.id);
    try {
      const res = await api<Broken>("/demo/break", { method: "POST", json: { scenario_id: s.id } });
      setBroken((b) => ({ ...b, [s.id]: res }));
      toast.ok(`${s.title}: deploy failed`, "A bad commit and a failed deploy went through the ingest pipeline.");
      refreshAll();
    } catch (e) {
      toast.error("Could not run the scenario", (e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    if (!window.confirm("Reset demo data? All demo deploys, incidents and investigations are wiped and reseeded.")) return;
    setBusy("reset");
    try {
      await api("/demo/reset", { method: "POST" });
      setBroken({});
      toast.ok("Demo data reset");
      refreshAll();
    } catch (e) {
      toast.error("Reset failed", (e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  if (system.data && !system.data.demo_mode) {
    return (
      <>
        <PageHeader title="Chaos lab" />
        <Panel>
          <Empty icon={<FlaskConical size={18} />} title="Demo mode is off">
            The chaos lab scripts failures against sample data. Set <code className="font-mono text-fg">OPSCEND_DEMO=1</code> in your .env and restart the API to use it.
          </Empty>
        </Panel>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Chaos lab"
        description="Five scripted failures. Each pushes a bad commit and a failed deploy through the real webhook pipeline, then waits for you to investigate."
        actions={
          <Button loading={busy === "reset"} onClick={reset}>
            <RotateCcw size={13} /> Reset demo data
          </Button>
        }
      />

      {system.data && !system.data.ai.configured && (
        <div className="mb-4 rounded-xl border border-warn/30 bg-warn/[0.06] px-4 py-3 text-[13px] leading-relaxed">
          <span className="font-medium text-warn">No LLM key set.</span> You can break deploys and read logs, but Investigate needs{" "}
          <code className="font-mono text-fg">GROQ_API_KEY</code> in your .env. Restart the API after adding it.
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {!scenarios.data && !scenarios.error && [0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-44 rounded-xl" />)}
        {scenarios.error && <Panel className="sm:col-span-2 lg:col-span-3"><Empty title="Could not load scenarios">{scenarios.error.message}</Empty></Panel>}
        {scenarios.data?.map((s, i) => {
          const b = broken[s.id];
          return (
            <motion.div key={s.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <Spotlight className="panel flex h-full flex-col p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] text-faint">{String(i + 1).padStart(2, "0")}</span>
                  {b ? <Tag color="var(--err)">broken</Tag> : <Tag>armed</Tag>}
                </div>
                <div className="mt-3 text-[15px] font-medium">{s.title}</div>
                <p className="mt-1.5 flex-1 text-[12.5px] leading-relaxed text-muted">{s.description}</p>
                <div className="mt-4 flex items-center gap-2">
                  {b ? (
                    <>
                      <InvestigateButton deploymentId={b.deployment_id} size="md" />
                      <ButtonLink href={`/console/deployments/${b.deployment_id}`}>Logs</ButtonLink>
                      <Button variant="ghost" loading={busy === s.id} onClick={() => breakIt(s)}>
                        Again
                      </Button>
                    </>
                  ) : (
                    <Button variant="danger" loading={busy === s.id} onClick={() => breakIt(s)}>
                      {busy !== s.id && <Bomb size={13} />} Break it
                    </Button>
                  )}
                </div>
              </Spotlight>
            </motion.div>
          );
        })}
      </div>

      <p className="mt-5 text-[12.5px] text-muted">
        Watch them land on the{" "}
        <Link href="/console/timeline" className="text-fg underline decoration-line underline-offset-4 hover:decoration-accent">
          timeline
        </Link>{" "}
        and in the{" "}
        <Link href="/console/events" className="text-fg underline decoration-line underline-offset-4 hover:decoration-accent">
          event inspector
        </Link>
        .
      </p>
    </>
  );
}
