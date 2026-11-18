"use client";

import { Reveal, SectionHeading } from "./reveal";

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
  { id: "poll", x: 280, y: 210, title: "Poller", sub: "reconcile every 30s" },
  { id: "worker", x: 540, y: 144, title: "Worker", sub: "normalize · upsert", color: "var(--accent)" },
  { id: "db", x: 800, y: 30, title: "Postgres", sub: "one deploy model" },
  { id: "ui", x: 800, y: 144, title: "Console", sub: "timeline · incidents" },
  { id: "ai", x: 800, y: 258, title: "Investigator", sub: "read-only tools", color: "var(--accent)" },
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
    <section id="how" className="relative px-4 py-28">
      <SectionHeading eyebrow="How it works" lead="Three providers, one worker." rest="Webhook handlers do almost nothing; a slow API or a duplicate delivery never breaks ingestion." />

      <Reveal delay={0.1} className="mx-auto mt-14 max-w-6xl">
        <div className="panel bg-dots relative overflow-x-auto p-4 sm:p-8">
          <svg viewBox="0 0 990 340" className="mx-auto block w-full min-w-[720px]" role="img" aria-label="Events flow from Vercel, Railway and GitHub through webhooks and a poller into one worker, then to Postgres, the console and the investigator.">
            {EDGES.map(([from, to, tone], i) => {
              const d = path(byId[from], byId[to]);
              const color = tone ? "var(--accent)" : "var(--muted)";
              return (
                <g key={`${from}-${to}`}>
                  <path d={d} fill="none" stroke="var(--line)" strokeWidth="1" />
                  <path d={d} fill="none" stroke={color} strokeWidth="1" strokeOpacity="0.35" strokeDasharray="3 7">
                    <animate attributeName="stroke-dashoffset" from="0" to="-100" dur="6s" repeatCount="indefinite" />
                  </path>
                  <circle r="2.6" fill={color}>
                    <animateMotion dur={`${2.4 + (i % 4) * 0.55}s`} begin={`${(i * 0.37) % 2.2}s`} repeatCount="indefinite" path={d} />
                    <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur={`${2.4 + (i % 4) * 0.55}s`} begin={`${(i * 0.37) % 2.2}s`} repeatCount="indefinite" />
                  </circle>
                </g>
              );
            })}
            {NODES.map((n) => (
              <g key={n.id} transform={`translate(${n.x},${n.y})`}>
                <rect width={W} height={H} rx="10" fill="var(--surface)" stroke={n.color === "var(--accent)" ? "color-mix(in oklab, var(--accent) 45%, var(--line))" : "var(--line)"} />
                <circle cx="18" cy={H / 2} r="4" fill={n.color ?? "var(--faint)"} />
                {n.color === "var(--accent)" && (
                  <circle cx="18" cy={H / 2} r="4" fill="none" stroke="var(--accent)">
                    <animate attributeName="r" values="4;11" dur="2s" repeatCount="indefinite" />
                    <animate attributeName="opacity" values="0.7;0" dur="2s" repeatCount="indefinite" />
                  </circle>
                )}
                <text x="34" y="22" fill="var(--fg)" fontSize="13" fontWeight="500" fontFamily="var(--font-sans)">
                  {n.title}
                </text>
                <text x="34" y="38" fill="var(--muted)" fontSize="10.5" fontFamily="var(--font-mono)">
                  {n.sub}
                </text>
              </g>
            ))}
          </svg>
        </div>
      </Reveal>

      <div className="mx-auto mt-4 grid max-w-6xl gap-4 sm:grid-cols-3">
        {[
          { k: "01", t: "Arrive twice, land once", d: "Every webhook and poll result is stored raw with a dedup key before anything else happens. Replays are free." },
          { k: "02", t: "One deploy model", d: "A REST API and a GraphQL API normalize into the same Deployment row, unique on provider and external id." },
          { k: "03", t: "Incidents open themselves", d: "A failed deploy or two failed health checks open one incident per service. A healthy deploy closes it." },
        ].map((c, i) => (
          <Reveal key={c.k} delay={0.08 * i}>
            <div className="panel h-full p-5">
              <div className="label-mono text-accent">{c.k}</div>
              <div className="mt-3 text-[15px] font-medium">{c.t}</div>
              <p className="mt-2 text-[13.5px] leading-relaxed text-muted">{c.d}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
