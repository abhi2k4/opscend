/** Tiny static-snippet highlighter for the landing page and diff views. Not a parser. */

const KEYWORDS: Record<string, string[]> = {
  python: ["class", "def", "async", "await", "return", "import", "from", "for", "in", "if", "else", "raise", "with", "as", "None", "True", "False", "not", "and", "or", "self"],
  bash: ["curl", "git", "docker", "cp", "cd", "make", "export", "open"],
  json: ["true", "false", "null"],
  yaml: [],
  ts: ["import", "from", "export", "const", "async", "await", "return", "new", "type", "interface", "function"],
};

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function highlight(code: string, lang: keyof typeof KEYWORDS | string): string {
  const kw = KEYWORDS[lang] ?? [];
  const comment = lang === "json" ? null : lang === "ts" ? /\/\/.*$/ : /#.*$/;
  return code
    .split("\n")
    .map((line) => {
      let rest = line;
      let tail = "";
      if (comment) {
        const m = rest.match(comment);
        // Only treat as a comment when the marker is not inside a string.
        if (m && m.index !== undefined && (rest.slice(0, m.index).match(/"/g)?.length ?? 0) % 2 === 0) {
          tail = `<span class="tok-c">${esc(rest.slice(m.index))}</span>`;
          rest = rest.slice(0, m.index);
        }
      }
      const parts = rest.split(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g);
      const body = parts
        .map((p, i) => {
          if (i % 2 === 1) return `<span class="tok-s">${esc(p)}</span>`;
          // One pass over word-ish tokens so inserted markup is never re-matched.
          return esc(p).replace(/\b(\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)\b(\()?/g, (m, word: string, paren?: string) => {
            const cls = /^\d/.test(word) ? "tok-n" : kw.includes(word) ? "tok-k" : paren ? "tok-f" : /^[A-Z][a-z]/.test(word) ? "tok-t" : null;
            if (word === "amp" || word === "lt" || word === "gt") return m;
            return cls ? `<span class="${cls}">${word}</span>${paren ?? ""}` : m;
          });
        })
        .join("");
      return body + tail;
    })
    .join("\n");
}
