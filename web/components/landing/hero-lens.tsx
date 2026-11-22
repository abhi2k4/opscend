"use client";

import { useEffect, useRef } from "react";

/**
 * The hero's backdrop: a wall of scrambled log noise, and a magnifying glass.
 *
 * Under the glass the noise resolves into readable log lines. One of them is the
 * line that broke the deploy; hold the glass over it and `onFound` fires. The glass
 * follows the pointer, and looks around by itself when nobody is steering.
 *
 * Two layers are painted once to offscreen canvases (the noise and the truth), so a
 * frame is two image draws and a clip, not thousands of text calls.
 */

const FONT_PX = 12.5;
const ROW_H = 20;
const NOISE = "/\\|<>=+*#%&@$?!~^:;{}[]01";
const PHRASES = [
  "clone repository",
  "restore cache",
  "install dependencies",
  "resolve packages",
  "run build",
  "compile ok",
  "bundle assets",
  "run migrations",
  "start server",
  "listening on $PORT",
  "health check 200",
  "upload artifacts",
  "deploy ready",
  "route traffic",
];
const CULPRIT = "error: exit code 1";

const WIDE = 1024; // below this the copy takes the full width and the glass works underneath it
const HOLD_MS = 320; // how long the glass must rest on the line to count
const SHOW_MS = 4200; // how long the found line stays lit before it hides again
const IDLE_MS = 3500; // after this long without the pointer, the glass looks around by itself

interface Scene {
  w: number;
  h: number;
  dpr: number;
  cw: number;
  cols: number;
  rows: number;
  noise: HTMLCanvasElement;
  truth: HTMLCanvasElement;
  culprit: { col: number; row: number; x: number; y: number };
}

const pick = <T,>(items: readonly T[] | string) => items[Math.floor(Math.random() * items.length)];

export function HeroLens({ onFound, reduce }: { onFound: (found: boolean) => void; reduce: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const report = useRef(onFound);
  report.current = onFound;

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = canvas?.parentElement;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !host || !ctx) return;

    const css = getComputedStyle(host);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const C = { bg: color("--bg"), dim: color("--line"), text: color("--muted"), signal: color("--signal"), fg: color("--fg") };
    const family = `${css.getPropertyValue("--font-plex-mono").trim() || "ui-monospace"}, ui-monospace, monospace`;
    const font = `${FONT_PX}px ${family}`;

    let scene: Scene | null = null;
    let raf = 0;
    let visible = true;
    let last = performance.now();
    let shimmerAt = 0;
    const pos = { x: 0, y: 0 };
    const pointer = { x: 0, y: 0, at: -Infinity };
    let over = 0; // ms the glass has rested on the culprit
    let foundAt = -Infinity;

    const radius = () => (scene && scene.w < 640 ? 94 : 112);

    function placeCulprit(s: Pick<Scene, "cols" | "rows" | "cw" | "w">) {
      // Keep it clear of the headline: right-hand side on wide screens, lower half on narrow ones.
      const wide = s.w >= WIDE;
      // Far enough from both edges that the whole glass fits on screen when it rests on the line.
      const edge = Math.ceil(((s.w < 640 ? 94 : 112) + 12) / s.cw - CULPRIT.length / 2);
      const minCol = Math.max(edge, wide ? Math.floor(s.cols * 0.56) : 1);
      const maxCol = Math.max(minCol, s.cols - CULPRIT.length - edge - 1);
      const col = minCol + Math.floor(Math.random() * (maxCol - minCol + 1));
      const minRow = Math.floor(s.rows * (wide ? 0.2 : 0.74));
      const maxRow = Math.max(minRow, Math.floor(s.rows * (wide ? 0.62 : 0.84)));
      const row = minRow + Math.floor(Math.random() * (maxRow - minRow + 1));
      return { col, row, x: (col + CULPRIT.length / 2) * s.cw, y: row * ROW_H + ROW_H / 2 };
    }

    function layer(w: number, h: number, dpr: number) {
      const c = document.createElement("canvas");
      c.width = Math.ceil(w * dpr);
      c.height = Math.ceil(h * dpr);
      const g = c.getContext("2d")!;
      g.scale(dpr, dpr);
      g.font = font;
      g.textBaseline = "middle";
      return [c, g] as const;
    }

    function paintTruth(s: Scene) {
      const g = s.truth.getContext("2d")!;
      g.clearRect(0, 0, s.w, s.h);
      for (let r = 0; r < s.rows; r++) {
        let line = "";
        while (line.length < s.cols) line += `${pick(PHRASES)}  ·  `;
        const y = r * ROW_H + ROW_H / 2;
        g.fillStyle = C.text;
        if (r === s.culprit.row) {
          const before = line.slice(0, Math.max(0, s.culprit.col - 2));
          const afterCol = s.culprit.col + CULPRIT.length + 2;
          g.fillText(before, 0, y);
          g.fillText(line.slice(afterCol), afterCol * s.cw, y);
          g.fillStyle = C.signal;
          g.fillText(CULPRIT, s.culprit.col * s.cw, y);
        } else {
          g.fillText(line, 0, y);
        }
      }
    }

    function paintNoiseCell(s: Scene, col: number, row: number) {
      const g = s.noise.getContext("2d")!;
      g.clearRect(col * s.cw, row * ROW_H, s.cw, ROW_H);
      // A faint tint where the culprit hides: a clue for anyone looking closely.
      const hint = row === s.culprit.row && col >= s.culprit.col && col < s.culprit.col + CULPRIT.length;
      g.globalAlpha = hint ? 0.5 : 1;
      g.fillStyle = hint ? C.signal : C.dim;
      g.fillText(pick(NOISE), col * s.cw, row * ROW_H + ROW_H / 2);
      g.globalAlpha = 1;
    }

    function build() {
      const w = host!.clientWidth;
      const h = host!.clientHeight;
      if (!w || !h) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas!.width = Math.ceil(w * dpr);
      canvas!.height = Math.ceil(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx!.font = font;
      const cw = ctx!.measureText("M").width || FONT_PX * 0.6;
      const cols = Math.ceil(w / cw) + 1;
      const rows = Math.ceil(h / ROW_H) + 1;
      const [noise] = layer(w, h, dpr);
      const [truth] = layer(w, h, dpr);
      const partial = { w, h, dpr, cw, cols, rows, noise, truth };
      scene = { ...partial, culprit: placeCulprit(partial) };
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) paintNoiseCell(scene, c, r);
      paintTruth(scene);
      if (!pos.x && !pos.y) Object.assign(pos, reduce ? { x: scene.culprit.x, y: scene.culprit.y } : { x: w * (w >= WIDE ? 0.86 : 0.5), y: h * (w >= WIDE ? 0.3 : 0.77) });
      draw(performance.now());
    }

    function relocate() {
      if (!scene) return;
      const old = scene.culprit;
      scene.culprit = placeCulprit(scene);
      for (let c = old.col; c < old.col + CULPRIT.length; c++) paintNoiseCell(scene, c, old.row);
      for (let c = scene.culprit.col; c < scene.culprit.col + CULPRIT.length; c++) paintNoiseCell(scene, c, scene.culprit.row);
      paintTruth(scene);
    }

    function draw(now: number) {
      const s = scene;
      if (!s) return;
      const r = radius();
      const showing = now - foundAt < SHOW_MS;
      ctx!.clearRect(0, 0, s.w, s.h);
      ctx!.drawImage(s.noise, 0, 0, s.w, s.h);
      // Quieten the noise behind the copy: it fades in away from the text.
      const wide = s.w >= WIDE;
      const fade = wide ? ctx!.createLinearGradient(0, 0, s.w * 0.66, 0) : ctx!.createLinearGradient(0, 0, 0, s.h * 0.76);
      fade.addColorStop(0, C.bg);
      fade.addColorStop(wide ? 0.45 : 0.9, C.bg);
      fade.addColorStop(1, "transparent");
      ctx!.globalAlpha = 0.94;
      ctx!.fillStyle = fade;
      ctx!.fillRect(0, 0, s.w, s.h);
      ctx!.globalAlpha = 1;

      // The glass: clear the noise, then show the truth slightly enlarged.
      ctx!.save();
      ctx!.beginPath();
      ctx!.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx!.clip();
      ctx!.fillStyle = C.bg;
      ctx!.fillRect(pos.x - r, pos.y - r, r * 2, r * 2);
      const zoom = 1.16;
      ctx!.translate(pos.x, pos.y);
      ctx!.scale(zoom, zoom);
      ctx!.translate(-pos.x, -pos.y);
      ctx!.drawImage(s.truth, 0, 0, s.w, s.h);
      ctx!.restore();

      // Handle first, so the ring sits on top of it.
      const a = Math.PI / 4;
      ctx!.lineCap = "butt";
      ctx!.strokeStyle = C.text;
      ctx!.lineWidth = 9;
      ctx!.beginPath();
      ctx!.moveTo(pos.x + Math.cos(a) * (r + 2), pos.y + Math.sin(a) * (r + 2));
      ctx!.lineTo(pos.x + Math.cos(a) * (r + 58), pos.y + Math.sin(a) * (r + 58));
      ctx!.stroke();
      ctx!.strokeStyle = C.signal;
      ctx!.lineWidth = 5;
      ctx!.beginPath();
      ctx!.arc(pos.x, pos.y, r, 0, Math.PI * 2);
      ctx!.stroke();

      if (showing) {
        // Once found, the line stays lit where it is. Inside the glass the enlarged copy
        // already shows it, so this one is drawn only outside the ring.
        const x = s.culprit.col * s.cw;
        const y = s.culprit.row * ROW_H;
        const width = CULPRIT.length * s.cw;
        ctx!.save();
        ctx!.beginPath();
        ctx!.rect(0, 0, s.w, s.h);
        ctx!.arc(pos.x, pos.y, r + 3, 0, Math.PI * 2);
        ctx!.clip("evenodd");
        ctx!.fillStyle = C.bg;
        ctx!.fillRect(x - 6, y, width + 12, ROW_H);
        ctx!.fillStyle = C.signal;
        ctx!.font = font;
        ctx!.textBaseline = "middle";
        ctx!.fillText(CULPRIT, x, y + ROW_H / 2);
        ctx!.fillRect(x - 6, y + ROW_H + 2, (width + 12) * Math.min(1, (now - foundAt) / 380), 2);
        ctx!.restore();
      }
    }

    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      const s = scene;
      if (!s || !visible) return;
      const dt = Math.min(64, now - last);
      last = now;

      if (now - shimmerAt > 110) {
        shimmerAt = now;
        const count = Math.ceil(s.cols * s.rows * 0.012);
        for (let i = 0; i < count; i++) paintNoiseCell(s, Math.floor(Math.random() * s.cols), Math.floor(Math.random() * s.rows));
      }

      const steering = now - pointer.at < IDLE_MS;
      const showing = now - foundAt < SHOW_MS;
      let tx = pointer.x;
      let ty = pointer.y;
      if (showing && !steering) {
        tx = s.culprit.x;
        ty = s.culprit.y;
      } else if (!steering) {
        // Wander the right-hand side, and close in on the line every so often.
        const wide = s.w >= WIDE;
        const phase = now % 12000;
        if (phase > 8200) {
          tx = s.culprit.x;
          ty = s.culprit.y;
        } else {
          tx = s.w * ((wide ? 0.72 : 0.5) + (wide ? 0.2 : 0.3) * Math.sin(now * 0.00037));
          ty = s.h * ((wide ? 0.46 : 0.77) + (wide ? 0.3 : 0.06) * Math.sin(now * 0.00053 + 1.3));
        }
      }
      const ease = 1 - Math.exp(-dt * (steering ? 0.012 : showing ? 0.006 : 0.0028));
      pos.x += (tx - pos.x) * ease;
      pos.y += (ty - pos.y) * ease;

      const near = Math.hypot(pos.x - s.culprit.x, pos.y - s.culprit.y) < radius() * 0.36;
      over = near && !showing ? over + dt : 0;
      if (over > HOLD_MS) {
        over = 0;
        foundAt = now;
        report.current(true);
      } else if (foundAt > 0 && !showing) {
        foundAt = -Infinity;
        report.current(false);
        relocate();
      }
      draw(now);
    }

    const onMove = (e: PointerEvent) => {
      if (e.pointerType === "touch") return;
      const box = host.getBoundingClientRect();
      pointer.x = e.clientX - box.left;
      pointer.y = e.clientY - box.top;
      pointer.at = performance.now();
    };
    const resize = new ResizeObserver(build);
    const view = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      last = performance.now();
    });

    let cancelled = false;
    // Measure the grid with the real font, or the columns drift when it swaps in.
    void document.fonts.ready.then(() => {
      if (cancelled) return;
      build();
      resize.observe(host);
      view.observe(host);
      if (!reduce) {
        host.addEventListener("pointermove", onMove);
        raf = requestAnimationFrame(frame);
      }
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      resize.disconnect();
      view.disconnect();
      host.removeEventListener("pointermove", onMove);
    };
  }, [reduce]);

  return <canvas ref={canvasRef} aria-hidden className="pointer-events-none absolute inset-0 size-full [mask-image:linear-gradient(to_bottom,black_86%,transparent)]" />;
}
