"use client";

import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { motion, useMotionValueEvent, useScroll } from "motion/react";
import { useState } from "react";
import { ButtonLink } from "@/components/ui/primitives";
import { ProviderIcon, Wordmark } from "@/components/ui/provider";
import { cn } from "@/lib/format";
import { API_DOCS_URL, REPO_URL } from "@/lib/site";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#investigator", label: "Investigator" },
  { href: "#integrations", label: "Integrations" },
  { href: "#quickstart", label: "Quickstart" },
];

export function Nav() {
  const { scrollY } = useScroll();
  const [scrolled, setScrolled] = useState(false);
  useMotionValueEvent(scrollY, "change", (v) => setScrolled(v > 24));

  return (
    <motion.header
      initial={{ y: -24, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.21, 0.6, 0.25, 1] }}
      className="fixed inset-x-0 top-0 z-50 px-4 pt-3"
    >
      <nav
        className={cn(
          "mx-auto flex h-12 max-w-6xl items-center justify-between rounded-xl border px-3 pl-4 transition-[background,border-color,backdrop-filter] duration-300",
          scrolled ? "border-line bg-bg/70 backdrop-blur-xl" : "border-transparent bg-transparent",
        )}
      >
        <Link href="/" aria-label="Opscend home">
          <Wordmark />
        </Link>
        <div className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="rounded-md px-3 py-1.5 text-[13px] text-muted transition-colors hover:text-fg">
              {l.label}
            </a>
          ))}
          <a href={API_DOCS_URL} className="rounded-md px-3 py-1.5 text-[13px] text-muted transition-colors hover:text-fg">
            API
          </a>
        </div>
        <div className="flex items-center gap-2">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden h-8 items-center gap-2 rounded-lg px-2.5 text-[13px] text-muted transition-colors hover:text-fg sm:inline-flex"
          >
            <ProviderIcon provider="github" size={15} className="!text-current" />
            Star
          </a>
          <ButtonLink href="/console" variant="primary" size="md">
            Open console <ArrowUpRight size={14} />
          </ButtonLink>
        </div>
      </nav>
    </motion.header>
  );
}
