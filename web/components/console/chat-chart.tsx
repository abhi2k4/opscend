"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/format";
import type { ChatChart } from "@/lib/types";

/**
 * A chart inside a chat answer. The data comes from the API (built by the chat tools
 * from stored records), so this only draws: stacked columns or a line, one y-axis,
 * a hover and keyboard readout for every series, and a table of the same numbers.
 */

// Status colours carry meaning here (ready, failed), so they always ship with a label.
const TONE: Record<ChatChart["series"][number]["tone"], string> = {
  ok: "var(--ok)",
  err: "var(--err)",
  info: "var(--info)",
  muted: "var(--muted)",
};

const HEIGHT = 190;
const PAD = { top: 10, right: 12, bottom: 24, left: 34 };
const BAR_MAX = 24;
const GAP = 2; // surface-coloured gap between stacked segments

/** Round tick values that cover `max`: 0, step, 2·step … */
function ticks(max: number): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power);
  const out: number[] = [];
  for (let v = 0; v < max + step; v += step) out.push(v);
  return out;
}

const fmt = (v: number | null) => (v === null ? "—" : Number.isInteger(v) ? String(v) : v.toFixed(1));

export function ChatChartView({ chart }: { chart: ChatChart }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(560);
  const [active, setActive] = useState<number | null>(null);
  const [table, setTable] = useState(false);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(Math.max(240, el.clientWidth)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const n = chart.categories.length;
  const { top, yTicks } = useMemo(() => {
    const totals = chart.categories.map((_, i) => (chart.kind === "bars" ? chart.series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0) : Math.max(...chart.series.map((s) => s.values[i] ?? 0))));
    const t = ticks(Math.max(...totals, 0));
    return { top: t[t.length - 1], yTicks: t };
  }, [chart]);

  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const band = plotW / n;
  const x = (i: number) => PAD.left + band * (i + 0.5);
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const barW = Math.max(2, Math.min(BAR_MAX, band - GAP));
  // Label as many categories as fit without touching; always the first.
  const every = Math.max(1, Math.ceil((Math.max(...chart.categories.map((c) => c.length)) * 6.4 + 14) / band));

  const move = (clientX: number) => {
    const box = wrap.current?.getBoundingClientRect();
    if (!box) return;
    setActive(Math.max(0, Math.min(n - 1, Math.floor((clientX - box.left - PAD.left) / band))));
  };

  // The readout sits beside the hovered position, never on top of the marks it describes.
  const offset = (chart.kind === "bars" ? Math.min(band, BAR_MAX + 16) / 2 : 0) + 10;
  const tipOnLeft = active !== null && x(active) + offset + 150 > width;
  const tipLeft = active === null ? 0 : x(active) + (tipOnLeft ? -offset : offset);

  return (
    <figure className="my-1 rounded-lg border border-line bg-surface">
      <figcaption className="flex items-start justify-between gap-3 px-3.5 pt-3">
        <div className="min-w-0">
          <div className="text-[13px] font-medium text-fg">{chart.title}</div>
          <div className="mt-0.5 font-mono text-[10.5px] text-muted">
            {chart.unit}
            {chart.subtitle ? ` · ${chart.subtitle}` : ""}
          </div>
        </div>
        <button type="button" onClick={() => setTable((t) => !t)} aria-pressed={table} className="shrink-0 rounded-md border border-line px-2 py-1 font-mono text-[10.5px] uppercase tracking-wider text-muted transition-colors hover:border-[var(--line-strong)] hover:text-fg">
          {table ? "Chart" : "Table"}
        </button>
      </figcaption>

      {chart.series.length > 1 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 px-3.5 pt-2 text-[11.5px] text-muted">
          {chart.series.map((s) => (
            <span key={s.name} className="inline-flex items-center gap-1.5">
              <span aria-hidden className={chart.kind === "line" ? "h-0.5 w-3" : "size-2 rounded-[1px]"} style={{ background: TONE[s.tone] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}

      {table ? (
        <div className="max-h-64 overflow-auto px-3.5 py-3">
          <table className="w-full text-left font-mono text-[11.5px]">
            <thead className="text-muted">
              <tr>
                <th className="py-1 pr-4 font-normal"> </th>
                {chart.series.map((s) => (
                  <th key={s.name} className="py-1 pr-4 text-right font-normal">
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {chart.categories.map((c, i) => (
                <tr key={`${c}-${i}`} className="border-t border-line-soft">
                  <td className="py-1 pr-4 text-fg/90">{c}</td>
                  {chart.series.map((s) => (
                    <td key={s.name} className="py-1 pr-4 text-right text-fg/90">
                      {fmt(s.values[i] ?? null)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          ref={wrap}
          className="relative mt-1 outline-none focus-visible:ring-1 focus-visible:ring-[var(--line-strong)]"
          tabIndex={0}
          role="img"
          aria-label={`${chart.title}. ${chart.series.map((s) => s.name).join(", ")} by ${n} points. Use the arrow keys to read values, or switch to the table.`}
          onPointerMove={(e) => move(e.clientX)}
          onPointerLeave={() => setActive(null)}
          onBlur={() => setActive(null)}
          onKeyDown={(e) => {
            if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
            e.preventDefault();
            setActive((a) => Math.max(0, Math.min(n - 1, (a ?? (e.key === "ArrowRight" ? -1 : n)) + (e.key === "ArrowRight" ? 1 : -1))));
          }}
        >
          <svg width={width} height={HEIGHT} className="block" aria-hidden>
            {yTicks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--line-strong)" : "var(--line-soft)"} strokeWidth={1} />
                <text x={PAD.left - 8} y={y(t) + 3.5} textAnchor="end" fontSize={10} fontFamily="var(--font-mono)" fill="var(--faint)">
                  {t}
                </text>
              </g>
            ))}

            {active !== null && chart.kind === "bars" && <rect x={PAD.left + band * active} y={PAD.top} width={band} height={plotH} fill="var(--raised)" />}
            {active !== null && chart.kind === "line" && <line x1={x(active)} x2={x(active)} y1={PAD.top} y2={PAD.top + plotH} stroke="var(--line-strong)" strokeWidth={1} />}

            {chart.kind === "bars" &&
              chart.categories.map((_, i) => {
                let base = 0;
                const present = chart.series.filter((s) => (s.values[i] ?? 0) > 0);
                return present.map((s, k) => {
                  const v = s.values[i] ?? 0;
                  const y1 = y(base + v);
                  const h = Math.max(1, y(base) - y1 - (k > 0 ? GAP : 0));
                  base += v;
                  const isTop = k === present.length - 1;
                  const r = isTop ? Math.min(3, barW / 2, h) : 0;
                  const left = x(i) - barW / 2;
                  // Rounded only at the data end; square where it meets the baseline or the gap.
                  const d = `M${left},${y1 + h} V${y1 + r} Q${left},${y1} ${left + r},${y1} H${left + barW - r} Q${left + barW},${y1} ${left + barW},${y1 + r} V${y1 + h} Z`;
                  return <path key={`${i}-${s.name}`} d={d} fill={TONE[s.tone]} opacity={active === null || active === i ? 1 : 0.55} />;
                });
              })}

            {chart.kind === "line" &&
              chart.series.map((s) => {
                // A null value (a failed check) breaks the line instead of drawing through it.
                const runs: string[] = [];
                let open = false;
                s.values.forEach((v, i) => {
                  if (v === null) {
                    open = false;
                    return;
                  }
                  runs.push(`${open ? "L" : "M"}${x(i)},${y(v)}`);
                  open = true;
                });
                return (
                  <g key={s.name}>
                    <path d={runs.join(" ")} fill="none" stroke={TONE[s.tone]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                    {s.values.map((v, i) => (v !== null && (active === i || (s.values[i - 1] ?? null) === null && (s.values[i + 1] ?? null) === null) ? <circle key={i} cx={x(i)} cy={y(v)} r={4} fill={TONE[s.tone]} stroke="var(--surface)" strokeWidth={2} /> : null))}
                  </g>
                );
              })}

            {chart.categories.map((c, i) =>
              i % every === 0 && x(i) + c.length * 3.2 < width ? (
                <text key={`${c}-${i}`} x={x(i)} y={HEIGHT - 8} textAnchor="middle" fontSize={10} fontFamily="var(--font-mono)" fill={active === i ? "var(--fg)" : "var(--faint)"}>
                  {c}
                </text>
              ) : null,
            )}
          </svg>

          {active !== null && (
            <div className={cn("pointer-events-none absolute top-2 z-10 min-w-[120px] rounded-md border border-[var(--line-strong)] bg-bg px-2.5 py-2", tipOnLeft && "-translate-x-full")} style={{ left: tipLeft }} role="status">
              <div className="mb-1 font-mono text-[10.5px] text-muted">{chart.categories[active]}</div>
              {chart.series.map((s) => (
                <div key={s.name} className="flex items-center gap-2 text-[11.5px] leading-5">
                  <span aria-hidden className="h-0.5 w-2.5" style={{ background: TONE[s.tone] }} />
                  <span className="font-mono font-medium text-fg">{fmt(s.values[active] ?? null)}</span>
                  <span className={cn("text-muted", chart.series.length === 1 && "sr-only")}>{s.name}</span>
                  {chart.series.length === 1 && <span className="text-muted">{chart.unit}</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </figure>
  );
}
