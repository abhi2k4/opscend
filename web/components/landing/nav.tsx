import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { Wordmark } from "@/components/ui/provider";
import { API_DOCS_URL, REPO_URL } from "@/lib/site";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#investigator", label: "Investigator" },
  { href: "#integrations", label: "Integrations" },
  { href: "#quickstart", label: "Quickstart" },
  { href: API_DOCS_URL, label: "API" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-line bg-bg">
      <nav className="mx-auto flex h-12 max-w-[1360px] items-stretch justify-between px-5 sm:px-8">
        <Link href="/" aria-label="Opscend home" className="flex items-center">
          <Wordmark />
        </Link>
        <div className="hidden items-stretch md:flex">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="label flex items-center border-l border-line px-5 transition-colors hover:bg-raised hover:text-fg">
              {l.label}
            </a>
          ))}
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="label flex items-center border-x border-line px-5 transition-colors hover:bg-raised hover:text-fg">
            GitHub
          </a>
        </div>
        <Link href="/console" className="label -mr-5 flex items-center gap-2 bg-fg px-5 !text-bg transition-opacity hover:opacity-85 sm:-mr-8">
          Console <ArrowUpRight size={13} />
        </Link>
      </nav>
    </header>
  );
}
