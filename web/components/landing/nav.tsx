import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Wordmark } from "@/components/ui/provider";
import { API_DOCS_URL, DOCS_URL, LANDING_ONLY, PRIMARY_CTA, REPO_URL } from "@/lib/site";

// Absolute anchors so the same bar works from /docs.
const LINKS = [
  { href: "/#how", label: "How it works" },
  { href: "/#investigator", label: "Investigator" },
  { href: "/#integrations", label: "Integrations" },
  // On the public site the main button already goes to the docs.
  ...(LANDING_ONLY ? [] : [{ href: DOCS_URL, label: "Docs" }, { href: API_DOCS_URL, label: "API" }]),
];

export function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg">
      <nav className="mx-auto flex h-12 max-w-[1120px] items-stretch justify-between px-6 sm:px-8">
        <Link href="/" aria-label="Opscend home" className="flex items-center">
          <Wordmark />
        </Link>
        <div className="hidden items-stretch md:flex">
          {LINKS.map((l) => {
            const cls = "label flex items-center border-l border-line px-5 transition-colors hover:bg-raised hover:text-fg";
            // The API reference is served by the backend, so it needs a full page load.
            return l.href === API_DOCS_URL ? (
              <a key={l.href} href={l.href} className={cls}>
                {l.label}
              </a>
            ) : (
              <Link key={l.href} href={l.href} className={cls}>
                {l.label}
              </Link>
            );
          })}
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="label flex items-center border-x border-line px-5 transition-colors hover:bg-raised hover:text-fg">
            GitHub
          </a>
        </div>
        <Link href={PRIMARY_CTA.href} className="label flex items-center gap-2 bg-fg px-5 !text-bg transition-opacity hover:opacity-85">
          {PRIMARY_CTA.short} <ArrowUpRight size={13} />
        </Link>
      </nav>
    </header>
  );
}
