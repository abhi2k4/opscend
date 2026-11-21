import { Sherlog } from "@/components/ui/sherlog";
import { Rise, Section } from "./reveal";

const RULES = [
  ["No write path", "Five read tools. Nothing else."],
  ["Evidence or nothing", "Every claim cites a log line, commit or deploy."],
  ["Bounded runs", "Eight tool calls, then it must answer."],
  ["Allowed to not know", "Inconclusive is a valid report."],
];

export function Investigator() {
  return (
    <Section
      id="investigator"
      no="02"
      label="Investigator"
      title={["It reads the logs.", "Then it shows", "its work."]}
      lead="Every step traced. Every claim cited."
    >
      <div className="grid grid-cols-1 border-t border-line lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <Rise className="flex items-center gap-6 border-b border-line py-8 lg:border-r lg:pr-10">
          <Sherlog size={132} className="shrink-0" />
          <div>
            <div className="label">Meet the investigator</div>
            <div className="display mt-2 text-[44px] sm:text-[56px]">Sherlog</div>
          </div>
        </Rise>

        <ol>
          {RULES.map(([title, body], i) => (
            <Rise key={title} delay={0.05 * i}>
              <li className="grid grid-cols-[44px_1fr] border-b border-line py-5 lg:pl-10">
                <span className="mono pt-1 text-[11.5px] text-faint">2.{i + 1}</span>
                <div>
                  <div className="text-[16px] font-medium">{title}</div>
                  <p className="mt-1.5 max-w-md text-[14px] leading-relaxed text-muted">{body}</p>
                </div>
              </li>
            </Rise>
          ))}
        </ol>
      </div>
    </Section>
  );
}
