import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Footer } from "@/components/landing/closing";
import { CodeBlock } from "@/components/landing/code-block";
import { LandingFrame } from "@/components/landing/frame";
import { Nav } from "@/components/landing/nav";
import { Lines } from "@/components/landing/reveal";
import { Sherlog } from "@/components/ui/sherlog";
import { REPO_URL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Docs: run it yourself",
  description: "Set up Opscend on your own machine with Docker Compose: start it, sign in, connect providers and turn on the investigator.",
};

const STEPS = [
  { id: "need", title: "What you need" },
  { id: "start", title: "Start it" },
  { id: "sign-in", title: "Sign in" },
  { id: "providers", title: "Connect providers" },
  { id: "investigator", title: "Turn on the investigator" },
  { id: "break", title: "Break something" },
  { id: "email", title: "Email alerts" },
  { id: "no-docker", title: "Without Docker" },
];

const PROVIDERS = [
  { name: "Vercel", token: "Access token", href: "https://vercel.com/account/settings/tokens", gives: "Projects, deploys, build logs" },
  { name: "Railway", token: "Account or workspace token", href: "https://railway.com/account/tokens", gives: "Services, deploys, build and runtime logs" },
  { name: "Render", token: "API key", href: "https://dashboard.render.com/u/settings#api-keys", gives: "Services, deploys, build and runtime logs" },
  { name: "Fly.io", token: "Read-only access token", href: "https://fly.io/docs/security/tokens/", gives: "Apps, releases, recent runtime logs" },
  { name: "Netlify", token: "Personal access token", href: "https://app.netlify.com/user/applications#personal-access-tokens", gives: "Sites and deploys" },
  { name: "Cloudflare", token: "API token with Pages: Read, plus account ID", href: "https://dash.cloudflare.com/profile/api-tokens", gives: "Pages projects, deploys, build logs" },
  { name: "AWS", token: "Read-only IAM access key, plus region", href: "https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html", gives: "Amplify builds and logs, ECS rollouts" },
  { name: "GitHub", token: "Token with read access to repo contents", href: "https://github.com/settings/personal-access-tokens", gives: "Commits and diffs" },
];

function Step({ no, id, title, children }: { no: number; id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 border-t border-line py-10 first:border-t-0 first:pt-0">
      <div className="label mb-3">Step {String(no).padStart(2, "0")}</div>
      <h2 className="display text-[40px] sm:text-[48px]">{title}</h2>
      <div className="mt-6 max-w-2xl space-y-4 text-[15px] leading-relaxed text-muted [&_a]:text-fg [&_a]:underline [&_a]:decoration-line [&_a]:underline-offset-4 hover:[&_a]:decoration-fg [&_code]:font-mono [&_code]:text-[13px] [&_code]:text-fg">
        {children}
      </div>
    </section>
  );
}

export default function Docs() {
  return (
    <LandingFrame>
      <Nav />
      <main className="mx-auto max-w-[1360px] px-5 sm:px-8">
        <header className="relative border-b border-line py-12 lg:py-16">
          <Sherlog size={190} className="absolute bottom-6 right-0 hidden lg:block" title="Sherlog, the Opscend mascot" />
          <div className="label mb-6">
            <span className="text-fg">Docs</span>
            <span className="mx-2 text-faint">/</span>
            self-hosted setup
          </div>
          <h1 className="display text-[clamp(52px,9vw,132px)]">
            <Lines immediate lines={["Run it", "yourself."]} />
          </h1>
          <p className="mt-6 max-w-xl text-[17px] leading-relaxed text-muted">
            Opscend has no hosted version. It runs on your machine, with your tokens and your own model key. About ten minutes.
          </p>
        </header>

        <div className="grid grid-cols-1 gap-x-10 py-12 lg:grid-cols-12">
          <nav aria-label="Steps" className="hidden lg:col-span-3 lg:block">
            <ol className="mono sticky top-20 border-l border-line text-[12px] uppercase tracking-[0.1em]">
              {STEPS.map((s, i) => (
                <li key={s.id}>
                  <a href={`#${s.id}`} className="-ml-px flex gap-3 border-l border-transparent py-2 pl-4 text-muted transition-colors hover:border-fg hover:text-fg">
                    <span className="text-faint">{String(i + 1).padStart(2, "0")}</span>
                    {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <div className="min-w-0 lg:col-span-9">
            <Step no={1} id="need" title="What you need">
              <ul className="mono border-t border-line text-[13px]">
                {[
                  ["Docker", "Docker Desktop, or Docker Engine with Compose"],
                  ["Git", "to clone the repository"],
                  ["A Groq API key", "free, only needed for the AI investigator"],
                ].map(([k, v]) => (
                  <li key={k} className="grid grid-cols-[150px_1fr] gap-4 border-b border-line py-3">
                    <span className="text-fg">{k}</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
            </Step>

            <Step no={2} id="start" title="Start it">
              <CodeBlock code={`git clone ${REPO_URL}.git\ncd opscend\ncp .env.example .env\ndocker compose up`} />
              <p>
                This starts Postgres, Redis, the API, a worker and the web app. Demo mode is on by default, so the console has sample deploys before you connect
                anything.
              </p>
              <p>
                Before connecting real providers, set <code>OPSCEND_SECRET_KEY</code> in <code>.env</code>. It encrypts your provider tokens, and changing it
                later makes stored tokens unreadable.
              </p>
              <CodeBlock code={`python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`} />
            </Step>

            <Step no={3} id="sign-in" title="Sign in">
              <p>
                Open <a href="http://localhost:3000">localhost:3000</a> and sign in with <code>OPSCEND_ADMIN_EMAIL</code> and <code>OPSCEND_ADMIN_PASSWORD</code> from
                your <code>.env</code>. There is one user. Change the password from its default before the machine is reachable by anyone else.
              </p>
            </Step>

            <Step no={4} id="providers" title="Connect providers">
              <p>In the console, open Integrations, pick a provider and paste a token. Opscend tests it, encrypts it and starts syncing.</p>
              <div className="border-t border-line">
                {PROVIDERS.map((p) => (
                  <div key={p.name} className="grid grid-cols-1 gap-x-6 gap-y-1 border-b border-line py-3.5 sm:grid-cols-[110px_1fr_1fr]">
                    <span className="font-medium text-fg">{p.name}</span>
                    <a href={p.href} target="_blank" rel="noreferrer">
                      {p.token}
                    </a>
                    <span className="mono text-[12.5px]">{p.gives}</span>
                  </div>
                ))}
              </div>
              <p>Deploys from the last seven days appear on the timeline within a minute. Railway project tokens are not supported.</p>
            </Step>

            <Step no={5} id="investigator" title="Turn on the investigator">
              <p>
                Create a key at <a href="https://console.groq.com/keys" target="_blank" rel="noreferrer">console.groq.com/keys</a>, add it to <code>.env</code>, then restart
                the API and worker.
              </p>
              <CodeBlock label=".env" code={`GROQ_API_KEY=your-key\n# optional: any tool-calling model your key can use\nOPSCEND_AI_MODEL=openai/gpt-oss-120b`} />
              <CodeBlock code="docker compose up -d api worker" />
              <p>
                Any OpenAI-compatible provider works through <code>OPSCEND_AI_BASE_URL</code>. On Groq's free tier a run takes 30 to 60 seconds.
              </p>
            </Step>

            <Step no={6} id="break" title="Break something">
              <p>
                Open the Chaos lab and run one of the five scripted failures. A failed deploy lands on the timeline and an incident opens. Click Investigate and
                watch the trace, then read the report.
              </p>
              <p>For the real thing, push a commit that breaks the build of a connected project.</p>
            </Step>

            <Step no={7} id="email" title="Email alerts">
              <p>Optional. Notifications always show under the bell in the console. To also get them by email, add your SMTP details and restart.</p>
              <CodeBlock
                label=".env"
                code={`OPSCEND_SMTP_HOST=smtp.example.com\nOPSCEND_SMTP_PORT=587\nOPSCEND_SMTP_USERNAME=you@example.com\nOPSCEND_SMTP_PASSWORD=app-password\nOPSCEND_EMAIL_TO=you@example.com`}
              />
              <p>Then use Send a test email on the Notifications page.</p>
            </Step>

            <Step no={8} id="no-docker" title="Without Docker">
              <p>
                For development you can skip Docker. The API falls back to SQLite and runs its jobs in-process. You need <code>uv</code> and <code>pnpm</code>.
              </p>
              <CodeBlock code={`cp .env.example .env\nmake dev-api\n# in a second terminal\nmake dev-web`} />
            </Step>
          </div>
        </div>
      </main>
      <Footer />
    </LandingFrame>
  );
}
