"use client";

import { Rise, Section } from "./reveal";

/**
 * Data-flow diagram: providers → webhooks / poller → worker → Postgres → console + investigator.
 * Pure SVG; the travelling dots are <animateMotion> so it costs no JS.
 */

interface Node {
  id: string;
  x: number;
  y: number;
  w?: number;
  title: string;
  sub: string;
  color?: string;
}

const W = 168;
const H = 52;

const NODES: Node[] = [
  { id: "vercel", x: 20, y: 30, title: "Vercel", sub: "REST · deploys", color: "var(--vercel)" },
  { id: "railway", x: 20, y: 144, title: "Railway", sub: "GraphQL · deploys", color: "var(--railway)" },
  { id: "github", x: 20, y: 258, title: "GitHub", sub: "REST · commits", color: "var(--github)" },
  { id: "hooks", x: 280, y: 78, title: "Webhooks", sub: "verify · dedup · 202" },
  { id: "poll", x: 280, y: 210, title: "Poller", sub: "reconcile every 60s" },
  { id: "worker", x: 540, y: 144, title: "Worker", sub: "normalize · upsert", color: "var(--fg)" },
  { id: "db", x: 800, y: 30, title: "Postgres", sub: "one deploy model" },
  { id: "ui", x: 800, y: 144, title: "Console", sub: "timeline · incidents" },
  { id: "ai", x: 800, y: 258, title: "Investigator", sub: "read-only tools", color: "var(--fg)" },
];

const EDGES: [string, string, string?][] = [
  ["vercel", "hooks"],
  ["railway", "hooks"],
  ["railway", "poll"],
  ["github", "hooks"],
  ["github", "poll"],
  ["vercel", "poll"],
  ["hooks", "worker", "accent"],
  ["poll", "worker", "accent"],
  ["worker", "db", "accent"],
  ["worker", "ui", "accent"],
  ["worker", "ai", "accent"],
];

const byId = Object.fromEntries(NODES.map((n) => [n.id, n]));

function path(a: Node, b: Node) {
  const x1 = a.x + W;
  const y1 = a.y + H / 2;
  const x2 = b.x;
  const y2 = b.y + H / 2;
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}

export function Flow() {
  return (
    <Section
      id="how"
      no="01"
      label="How it works"
      title={["Three providers,", "one worker."]}
      lead="Webhooks verify, store and enqueue. The worker does the rest."
    >
      <Rise>
        <div className="label mb-3">Fig. 2 — data flow</div>
        <div className="overflow-x-auto border border-line bg-surface p-4 sm:p-8">
          <svg viewBox="0 0 990 340" className="mx-auto block w-full min-w-[720px]" role="img" aria-label="Events flow from Vercel, Railway and GitHub through webhooks and a poller into one worker, then to Postgres, the console and the investigator.">
            {EDGES.map(([from, to, tone], i) => {
              const d = path(byId[from], byId[to]);
              const dur = `${2.6 + (i % 4) * 0.6}s`;
              const begin = `${(i * 0.37) % 2.2}s`;
              return (
                <g key={`${from}-${to}`}>
                  <path d={d} fill="none" stroke="var(--line)" strokeWidth="1" />
                  <rect x="-2.5" y="-2.5" width="5" height="5" opacity="0" fill={tone ? "var(--fg)" : "var(--muted)"}>
                    <animateMotion dur={dur} begin={begin} repeatCount="indefinite" path={d} />
                    <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={dur} begin={begin} repeatCount="indefinite" />
                  </rect>
                </g>
              );
            })}
            {NODES.map((n) => {
              const core = n.color === "var(--fg)";
              return (
                <g key={n.id} transform={`translate(${n.x},${n.y})`}>
                  <rect width={W} height={H} fill={core ? "var(--fg)" : "var(--bg)"} stroke={core ? "var(--fg)" : "var(--line)"} />
                  <rect x="14" y={H / 2 - 4} width="8" height="8" fill={core ? "var(--bg)" : (n.color ?? "var(--faint)")} />
                  <text x="34" y="22" fill={core ? "var(--bg)" : "var(--fg)"} fontSize="13" fontWeight="600" fontFamily="var(--font-sans)">
                    {n.title}
                  </text>
                  <text x="34" y="38" fill={core ? "var(--bg)" : "var(--muted)"} opacity={core ? 0.7 : 1} fontSize="10.5" fontFamily="var(--font-plex-mono)">
                    {n.sub}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </Rise>

      <div className="mt-10 grid grid-cols-1 border-t border-line md:grid-cols-3">
        {[
          { k: "a", t: "Arrive twice, land once", d: "Every event is stored under a dedup key first." },
          { k: "b", t: "One deploy model", d: "REST and GraphQL normalize into the same row." },
          { k: "c", t: "Incidents open themselves", d: "A failed deploy opens one. A healthy deploy closes it." },
        ].map((c, i) => (
          <Rise key={c.k} delay={0.07 * i} className={`border-b border-line py-6 md:py-8 ${i > 0 ? "md:border-l md:pl-8" : ""} md:pr-8`}>
            <div className="label">1.{c.k}</div>
            <div className="mt-4 text-[17px] font-medium">{c.t}</div>
            <p className="mt-2 text-[14px] leading-relaxed text-muted">{c.d}</p>
          </Rise>
        ))}
      </div>
    </Section>
  );
}
