"use client";

import { CopyButton } from "@/components/ui/primitives";

/** Terminal-style block with a copy button. Lines starting with "#" render as comments. */
export function CodeBlock({ code, label = "Terminal" }: { code: string; label?: string }) {
  const lines = code.trim().split("\n");
  const copyable = lines.filter((l) => !l.startsWith("#")).join("\n");
  const shell = label === "Terminal";
  return (
    <div className="border border-line bg-surface">
      <div className="label flex h-9 items-center justify-between border-b border-line pl-4 pr-1.5">
        <span>{label}</span>
        <CopyButton value={copyable} label="Copy" />
      </div>
      <pre className="mono overflow-x-auto p-4 text-[12.5px] leading-[1.8]">
        {lines.map((line, i) =>
          line.startsWith("#") ? (
            <div key={i} className="text-faint">
              {line}
            </div>
          ) : (
            <div key={i}>
              {shell && <span className="mr-3 select-none text-faint">$</span>}
              {line}
            </div>
          ),
        )}
      </pre>
    </div>
  );
}
