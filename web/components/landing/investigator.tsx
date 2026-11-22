import { Sherlog } from "@/components/ui/sherlog";
import { Rise, Section } from "./reveal";

const PROMISES = [
  ["It reads. It never writes.", "Sherlog can look at logs, diffs and deploys. It has no way to change anything."],
  ["It shows its evidence.", "Every claim links to the log line or commit behind it, so you can check it in a click."],
  ["It says when it doesn't know.", "No evidence, no verdict. You get “inconclusive” and what was missing."],
];

export function Investigator() {
  return (
    <Section
      id="investigator"
      label="The investigator"
      title={["Meet Sherlog."]}
      lead="When a deploy fails, Sherlog reads the logs and the diff for you, then tells you what it found and how sure it is."
    >
      <div className="grid grid-cols-1 items-center gap-x-20 gap-y-12 lg:grid-cols-[auto_1fr]">
        <Rise className="flex justify-center lg:justify-start">
          <Sherlog size={240} />
        </Rise>
        <ul className="space-y-9">
          {PROMISES.map(([title, body], i) => (
            <Rise key={title} delay={0.08 * i}>
              <li className="grid grid-cols-[20px_1fr] gap-x-4">
                <span aria-hidden className="mt-[9px] size-2 bg-[var(--signal)]" />
                <div>
                  <h3 className="text-[20px] font-medium">{title}</h3>
                  <p className="mt-2 max-w-lg text-[16px] leading-[1.65] text-fg/70">{body}</p>
                </div>
              </li>
            </Rise>
          ))}
        </ul>
      </div>
    </Section>
  );
}
