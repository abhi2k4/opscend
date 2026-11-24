"use client";

import Link from "next/link";
import { useNow } from "@/components/console/deploys";
import { Panel, PanelHeader, Tag } from "@/components/ui/primitives";
import { useApi } from "@/lib/api";
import { shortSha, timeAgo } from "@/lib/format";
import type { FixKind, SimilarIncident } from "@/lib/types";

const MATCH = { signature: "same error", family: "same kind of error", text: "similar error" } as const;
const FIX: Record<FixKind, string> = {
  redeploy: "redeploy, same commit",
  rollback: "rollback",
  code_change: "new code",
};

/** Earlier incidents with an error like this one's, and the deploy that resolved each. */
export function SimilarIncidents({ incidentId }: { incidentId: string }) {
  const { data } = useApi<SimilarIncident[]>(`/incidents/${incidentId}/similar`);
  const now = useNow();
  if (!data?.length) return null;

  return (
    <Panel className="mt-4">
      <PanelHeader title="Seen before" right={<span className="label-mono text-faint">a hint from past incidents, not evidence</span>} />
      {data.map(({ incident: past, match, resolved_by: fix }) => (
        <div key={past.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft px-4 py-3 last:border-0">
          <div className="min-w-0 flex-1 basis-[240px]">
            <div className="flex items-center gap-2 text-[13px]">
              <span className="truncate">{past.title}</span>
              <Tag color={match === "text" ? "var(--muted)" : "var(--accent)"}>{MATCH[match]}</Tag>
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-muted">
              {past.service_name} · opened {timeAgo(past.opened_at, now)}
              {fix && (
                <>
                  {" · resolved by "}
                  <Link href={`/console/deployments/${fix.id}`} className="text-fg hover:underline">
                    {shortSha(fix.commit_sha)}
                  </Link>
                  {past.fix_kind && <span className="text-faint"> ({FIX[past.fix_kind]})</span>}
                </>
              )}
            </div>
          </div>
          {past.investigation_id && (
            <Link href={`/console/investigations/${past.investigation_id}`} className="font-mono text-[11px] text-muted hover:text-fg">
              report →
            </Link>
          )}
        </div>
      ))}
    </Panel>
  );
}
