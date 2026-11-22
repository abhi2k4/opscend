import { Rise, Section } from "./reveal";

const STEPS = [
  {
    title: "Connect your platforms",
    body: "Paste a read-only token for each place you deploy, and for GitHub. That is the whole setup.",
  },
  {
    title: "Keep shipping",
    body: "Every deploy and commit lands on one timeline. Opscend watches health and opens an incident when something fails.",
  },
  {
    title: "Get the cause, not the alert",
    body: "A failed deploy is investigated straight away. You open the incident and the likely cause is already there, with the evidence.",
  },
];

/** How it works, as the three things that happen from the user's side. */
export function Story() {
  return (
    <Section id="how" label="How it works" title={["Three steps.", "Then it runs itself."]}>
      <ol className="grid grid-cols-1 gap-x-12 gap-y-14 md:grid-cols-3">
        {STEPS.map((step, i) => (
          <Rise key={step.title} delay={0.1 * i}>
            <li>
              <div aria-hidden className="display text-[84px] leading-none text-transparent [-webkit-text-stroke:1px_var(--line-strong)]">
                {i + 1}
              </div>
              <h3 className="mt-6 text-[20px] font-medium">{step.title}</h3>
              <p className="mt-3 max-w-sm text-[16px] leading-[1.65] text-fg/70">{step.body}</p>
            </li>
          </Rise>
        ))}
      </ol>
    </Section>
  );
}
