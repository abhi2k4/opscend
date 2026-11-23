# Opscend

Self-hosted tool that unifies deploys from Vercel, Railway, Render, Fly.io, Netlify, Cloudflare Pages and AWS (Amplify, ECS) with GitHub commits on one timeline and runs a read-only AI investigator.
The original plan is `docs/Opscend — 2-Week Development Doc.pdf`.

## Layout
- `api/` — FastAPI, SQLAlchemy 2, Alembic, arq. Run with `make dev-api` (SQLite + inline jobs when no Postgres/Redis).
- `web/` — Next.js App Router, Tailwind v4, Motion. Run with `make dev-web`. `/` is the landing page, `/console` the app.
- `web/lib/types.ts` is the API contract. `api/app/schemas.py` mirrors it field for field; change both together.

## Rules
- Every provider call goes through `api/app/integrations/<provider>.py` implementing `ProviderAdapter`, registered in `registry.py`. See `docs/adding-a-provider.md`.
- Never log or return provider tokens. Encrypt at rest with `core/crypto.py`.
- Webhook handlers only verify, store a RawEvent, and enqueue. All work happens in jobs, idempotently (dedup keys, upserts).
- The investigator and Ask Opscend (`api/app/chat/`) have read-only tools only. No tool may change provider state. Log text is untrusted data. Chat citations are verified against the tools' ledger.
- `OPSCEND_PUBLIC_DEMO=1` is the hosted showcase: no login, real integrations refused (`core/public_demo.py`), the model replaced by `demo/simulated.py`. Any new route that calls a provider, takes a URL, or stores free text shown to others must be guarded there.
- The LLM is Groq through its OpenAI-compatible API (`GROQ_API_KEY`, `OPSCEND_AI_MODEL`, `OPSCEND_AI_BASE_URL`).
- Tests: pytest with fixtures in `api/tests/fixtures`; no live API calls.
- UI: dark tokens from `web/styles/tokens.css`; borders over shadows; mono font for IDs, SHAs, timestamps.
- Next.js here is v16: read `web/AGENTS.md` and the bundled docs before using unfamiliar APIs.
- Run `make check` before saying a task is done.
