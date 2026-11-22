"use client";

import Link from "next/link";
import { useNow } from "@/components/console/deploys";
import { PageHeader } from "@/components/console/shell";
import { ButtonLink, ConfidenceMeter, Dot, Empty, Panel, Skeleton, Tag } from "@/components/ui/primitives";
import { Sherlog } from "@/components/ui/sherlog";
import { useApi } from "@/lib/api";
import { compact, duration, shortSha, timeAgo } from "@/lib/format";
import type { Investigation, InvestigationStats } from "@/lib/types";

const STATUS_COLOR = { queued: "var(--muted)", running: "var(--accent)", completed: "var(--ok)", failed: "var(--err)" } as const;

export default function InvestigationsPage() {
  const { data, error } = useApi<Investigation[]>("/investigations", { refreshInterval: 5000 });
  const stats = useApi<InvestigationStats>("/investigations/stats", { refreshInterval: 15000 }).data;
  const now = useNow();

  return (
    <>
      <PageHeader title="Investigations" description="Every run of the AI investigator, with its trace and cited report." />
      {stats && stats.completed > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
          {[
            ["Reports", String(stats.completed)],
            ["Inconclusive", String(stats.inconclusive)],
            ["Rated", `${stats.rated} of ${stats.completed}`],
            ["Marked right", stats.rated ? `${stats.helpful} of ${stats.rated}` : "not rated yet"],
          ].map(([label, value]) => (
            <div key={label} className="bg-surface px-4 py-3">
              <div className="label-mono mb-1">{label}</div>
              <div className="font-mono text-[13px]">{value}</div>
            </div>
          ))}
        </div>
      )}
      <Panel>
        {!data && !error && <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>}
        {error && !data && <Empty title="Could not load investigations">{error.message}</Empty>}
        {data?.length === 0 && (
          <Empty icon={<Sherlog size={34} animated={false} />} title="Sherlog has nothing to investigate yet" action={<ButtonLink href="/console/chaos" variant="primary">Open the chaos lab</ButtonLink>}>
            Open a failed deploy and click Investigate, or break one on purpose in the chaos lab.
          </Empty>
        )}
        {data?.map((inv) => (
          <Link key={inv.id} href={`/console/investigations/${inv.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-4 border-b border-line-soft px-4 py-3.5 transition-colors last:border-0 hover:bg-raised/50">
            <Tag color={STATUS_COLOR[inv.status]}>
              <Dot color={STATUS_COLOR[inv.status]} pulse={inv.status === "running"} className="scale-75" /> {inv.status}
            </Tag>
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[13.5px]">
                <span className="font-medium">{inv.service_name ?? "—"}</span>
                {inv.report?.culprit_commit_sha && <span className="font-mono text-[11.5px] text-accent">{shortSha(inv.report.culprit_commit_sha)}</span>}
              </div>
              <div className="mt-0.5 truncate text-[12.5px] text-muted">{inv.report?.summary ?? inv.report?.likely_cause ?? inv.error ?? "In progress…"}</div>
            </div>
            <div className="flex items-center gap-5 font-mono text-[11px] text-muted">
              {inv.feedback && <span className={inv.feedback.rating === "up" ? "text-ok" : "text-err"}>{inv.feedback.rating === "up" ? "right" : "wrong"}</span>}
              {inv.report && <span className="hidden sm:block"><ConfidenceMeter confidence={inv.report.confidence} /></span>}
              <span className="hidden w-14 text-right md:block">{compact(inv.tokens_used)} tok</span>
              <span className="hidden w-12 text-right md:block">{duration(inv.duration_ms)}</span>
              <span className="w-14 text-right text-faint">{timeAgo(inv.created_at, now)}</span>
            </div>
          </Link>
        ))}
      </Panel>
    </>
  );
}
