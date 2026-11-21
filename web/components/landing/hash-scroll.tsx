"use client";

import { useEffect } from "react";

/**
 * Lands on the section named in the URL hash (e.g. /#investigator).
 *
 * The browser's own jump happens before the fonts and the hero have settled, and
 * with smooth scrolling on it gets cut short near the top. So once layout is
 * stable we jump there ourselves, instantly, and once more shortly after in case
 * something above was still growing. Any input from the reader cancels that.
 */
export function HashScroll() {
  useEffect(() => {
    let cancelled = false;
    const cancel = () => (cancelled = true);
    const jump = () => {
      if (cancelled) return;
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (id) document.getElementById(id)?.scrollIntoView({ behavior: "instant", block: "start" });
    };
    const events = ["wheel", "touchstart", "keydown", "mousedown"] as const;
    events.forEach((e) => window.addEventListener(e, cancel, { passive: true, once: true }));

    const timers: ReturnType<typeof setTimeout>[] = [];
    (document.fonts?.ready ?? Promise.resolve()).then(() => {
      requestAnimationFrame(jump);
      timers.push(setTimeout(jump, 350), setTimeout(jump, 900));
    });
    return () => {
      cancel();
      timers.forEach(clearTimeout);
      events.forEach((e) => window.removeEventListener(e, cancel));
    };
  }, []);
  return null;
}
