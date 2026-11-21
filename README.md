# Opscend

**Know why the deploy broke.** Opscend is an open-source, self-hosted tool that puts every Vercel deploy, Railway deploy and GitHub commit on one timeline, opens an incident when something fails, and runs a read-only AI investigator that reads the logs and the diff and names the likely cause — citing its evidence.

> Single user, self-hosted, bring your own LLM key. The investigator has no write tools.

## Quick start

### With Docker

```bash
cp .env.example .env        # set GROQ_API_KEY and OPSCEND_SECRET_KEY
docker compose up
```

Open http://localhost:3000 and sign in with `OPSCEND_ADMIN_EMAIL` / `OPSCEND_ADMIN_PASSWORD` from your `.env`.

### Without Docker (local development)

No Postgres or Redis needed: the API falls back to SQLite and runs jobs in-process.

```bash
cp .env.example .env
make dev-api                # FastAPI on :8000  (needs uv)
make dev-web                # Next.js on :3000  (needs pnpm)
```

Demo mode (`OPSCEND_DEMO=1`, the default) seeds a sample storefront with a failed Railway deploy so every screen has data before you connect anything.

## What is in the box

| Screen | Route | What it does |
| --- | --- | --- |
| Landing | `/` | Pitch, animated demo, quick start |
| Overview | `/console` | Service health, open incidents, latest deploys |
| Ask Opscend | `/console/ask` | Chat with your deploy data: answers cite the deploys, log lines and commits they come from |
| Timeline | `/console/timeline` | Deploys, commits and incidents from all providers on one rail |
| Deploy detail | `/console/deployments/:id` | Build and runtime logs with level filters, commit diff, Investigate |
| Investigation | `/console/investigations/:id` | Live trace of every model turn and tool call, next to the cited report |
| Incidents | `/console/incidents` | Auto-opened on failed deploys and failed health checks |
| Notifications | `/console/notifications` | Bell in the top bar, full history, email alert status and a test button |
| Integrations | `/console/integrations` | Paste a token, test it, see the provider's capabilities |
| Event inspector | `/console/events` | Every raw webhook and poll result, with dedup state |
| Chaos lab | `/console/chaos` | Five scripted failures pushed through the real ingest pipeline |

Developer conveniences: `⌘K` command palette (type a question to send it to Ask Opscend), `g` + letter navigation, click-to-copy ids and SHAs, and interactive API docs at `/api/docs`.

## The AI investigator

- Runs on **Groq** through its OpenAI-compatible API. Set `GROQ_API_KEY`; change the model with `OPSCEND_AI_MODEL`, or point `OPSCEND_AI_BASE_URL` at any OpenAI-compatible endpoint.
- Five read-only tools: `get_deployment`, `get_logs`, `list_recent_deploys`, `get_commit_diff`, `get_health_history`.
- At most eight tool calls per run, with a token budget. Every step is stored as a span.
- The report must cite log lines, commits or deploys it actually saw, or say it is inconclusive.
- Log text is passed as untrusted data. Provider tokens never enter the model context.

## Ask Opscend

A chat assistant over everything Opscend has collected. Ask "which services had failed deploys this week?", "search the logs for ECONNREFUSED" or "what's our failure rate and recovery time per service?".

- Same model settings and limits as the investigator (`OPSCEND_AI_MAX_TOOL_CALLS`, `OPSCEND_AI_TOKEN_BUDGET`, per answer).
- The investigator's five tools plus six read-only query tools: `list_services`, `search_deployments`, `search_logs`, `list_incidents`, `list_commits`, `deploy_stats`. There is no free-form SQL.
- Every `[deploy:…]`, `[log:…]` or `[commit:…]` citation is checked against what the tools actually returned; invented ids are removed before the answer is saved.
- Answers run as jobs (like investigations) and the UI polls for progress, so they work the same with inline jobs and the arq worker.
- Log search covers stored lines. On Postgres it uses a trigram index (`pg_trgm`, created by migration 0004 when the database user is allowed to).

Stored log lines and health checks older than `OPSCEND_RETENTION_DAYS` (default 30, `0` keeps everything) are deleted hourly.

## Notifications and email alerts

Opened and resolved incidents, finished investigations and integration errors show up under the bell in the console. To also receive them by email, set the `OPSCEND_SMTP_*` and `OPSCEND_EMAIL_*` variables in `.env` (any SMTP provider works) and restart the API and worker. `OPSCEND_EMAIL_EVENTS` chooses which events are emailed.

To try it without a real mail account, start the bundled test inbox and point Opscend at it:

```bash
docker compose --profile mail up -d mailpit
```

Then set `OPSCEND_SMTP_HOST=mailpit`, `OPSCEND_SMTP_PORT=1025`, `OPSCEND_SMTP_SECURITY=none`, plus any from and to address, and read the mail at http://localhost:8025.

## Architecture

```
Vercel ─┐                 ┌─ Postgres ── Console (Next.js)
Railway ─┼─ webhooks ─┐    │
GitHub ─┘   poller  ──┴─ worker ──────── Investigator (Groq, read-only tools)
```

Webhook handlers verify the signature, store the raw event under a dedup key, and enqueue. All real work happens in the worker, idempotently, so a slow provider or a duplicate delivery never breaks ingestion.

```
api/   FastAPI · SQLAlchemy 2 · Alembic · arq
web/   Next.js App Router · Tailwind v4 · Motion
docs/  plan, provider guide
```

`web/lib/types.ts` is the API contract; `api/app/schemas.py` mirrors it.

## Adding a provider

A provider is one adapter file plus one registry line. See [docs/adding-a-provider.md](docs/adding-a-provider.md). The console reads the capability manifest from `/api/integrations/catalog`, so a new adapter shows up in Integrations without frontend changes.

## Development

```bash
make test      # pytest, no live API calls
make lint
make check     # everything CI runs
```

## Status

v0.1. Vercel, Railway and GitHub adapters are written against the providers' public APIs and tested with recorded-style fixtures. Not in scope: organizations, RBAC, alerting, any write action.
