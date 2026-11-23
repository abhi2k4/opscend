"""What the simulated investigator says about each scripted failure.

The public demo has no model behind it. These are the conclusions a real run reaches
on the scripted scenarios, written down once; the simulated run still calls the real
tools, and every log line it cites is looked up in what those tools returned.
"""

from dataclasses import dataclass

from .scenarios import SCENARIOS, STRIPE_ENV


@dataclass(frozen=True)
class Diagnosis:
    summary: str
    likely_cause: str  # `{short}` is replaced with the short commit sha
    suggested_fix: str
    log_fragments: tuple[str, ...]  # one log line containing each is cited
    diff_quote: str
    deploy_quote: str
    confidence: str = "high"


_BY_SCENARIO: dict[str, Diagnosis] = {
    "seeded-stripe-secret": Diagnosis(
        summary="storefront-api crashes at boot: STRIPE_WEBHOOK_SECRET is required but not set",
        likely_cause=(
            "Commit {short} made STRIPE_WEBHOOK_SECRET a required environment variable in "
            "apps/api/src/config/env.ts, but the variable is not set on the Railway service. "
            "The build succeeded; the container then exited with code 1 on every start while "
            "loading config, so the healthcheck never passed and Railway marked the deploy failed."
        ),
        suggested_fix=(
            "Set STRIPE_WEBHOOK_SECRET (the whsec_… signing secret from the Stripe dashboard) in "
            "the storefront-api service variables on Railway and redeploy. To avoid a repeat, "
            "validate required variables in CI against the production variable list."
        ),
        log_fragments=(
            "Error: Missing required environment variable STRIPE_WEBHOOK_SECRET",
            "config/env.js:21:28",
            "Healthcheck failed!",
        ),
        diff_quote='+  STRIPE_WEBHOOK_SECRET: required("STRIPE_WEBHOOK_SECRET"),',
        deploy_quote="Build finished normally; the failure is at container start.",
    ),
    "bad-env-var": Diagnosis(
        summary="storefront-api crashes at boot: it now reads CACHE_URL, which is not set",
        likely_cause=(
            "Commit {short} renamed the required variable REDIS_URL to CACHE_URL in "
            "apps/api/src/config/env.ts and apps/api/src/cache/client.ts, but only the code "
            "changed: the Railway service still defines REDIS_URL. The build passed, then the "
            "container threw while loading config on each of its three start attempts and the "
            "healthcheck failed."
        ),
        suggested_fix=(
            "Add CACHE_URL to the storefront-api variables on Railway with the value REDIS_URL "
            "has today, then redeploy. Remove REDIS_URL once the deploy is healthy, or keep "
            "reading it as a fallback for one release."
        ),
        log_fragments=(
            "Error: Missing required environment variable CACHE_URL",
            "config/env.js:17:16",
            "Healthcheck failed!",
        ),
        diff_quote='+  CACHE_URL: required("CACHE_URL"),',
        deploy_quote="Build finished normally; the failure is at container start.",
    ),
    "syntax-error": Diagnosis(
        summary="storefront-web fails to build: unclosed <p> tag in checkout/summary.tsx",
        likely_cause=(
            "Commit {short} added an estimated delivery line to "
            "apps/web/app/checkout/summary.tsx but never closed its <p> tag. Turbopack stops at "
            "summary.tsx:23 with a parse error, so the Next.js build exits with code 1 and "
            "Vercel never produces a deployment. Nothing reached production."
        ),
        suggested_fix=(
            "Close the tag (</p>) on line 22 of apps/web/app/checkout/summary.tsx and push. "
            "Running the type check or next build in CI before merge would have caught it."
        ),
        log_fragments=(
            "./app/checkout/summary.tsx:23:8",
            "Expected corresponding JSX closing tag for <p>",
            'Command "pnpm run build" exited with 1',
        ),
        diff_quote='+        <p className="eta">Arrives by {formatDate(cart.eta)}',
        deploy_quote="The failure is in the build step; no runtime logs exist.",
    ),
    "failing-migration": Diagnosis(
        summary="storefront-api release aborted: migration indexes a column that does not exist",
        likely_cause=(
            "Commit {short} added the migration 20261118093000_orders_customer_idx.sql, which "
            "creates an index on orders (customer_id, created_at). The orders table has no "
            "customer_id column (the same commit changes the query from user_id to customer_id), "
            "so Postgres rejects it with error 42703. The pre-deploy command failed and Railway "
            "aborted the deploy before starting the new container; the migration was rolled back."
        ),
        suggested_fix=(
            "Either index the existing user_id column, or add a migration that renames user_id "
            "to customer_id and run it before this one. The previous deploy is still live, so "
            "there is no need to roll back."
        ),
        log_fragments=(
            'error: column "customer_id" does not exist',
            "migrate: FAILED 20261118093000_orders_customer_idx.sql",
            "Pre-deploy command failed with exit code 1",
        ),
        diff_quote="+  ON orders (customer_id, created_at DESC);",
        deploy_quote="The image built; the failure is in the pre-deploy migration.",
    ),
    "dependency-bump": Diagnosis(
        summary="worker crashes at boot: bullmq 6 removed QueueScheduler",
        likely_cause=(
            "Commit {short} bumped bullmq from 4.17.0 to 6.0.1 in apps/worker/package.json. "
            "bullmq 6 no longer exports QueueScheduler, but "
            "apps/worker/dist/queues/scheduler.js still constructs one. The build passed "
            "because nothing checks that call at build time; the worker then threw a TypeError "
            "on each of its three start attempts."
        ),
        suggested_fix=(
            "Revert the bump to get the worker running, then migrate: delete the QueueScheduler "
            "construction in apps/worker/src/queues/scheduler.ts (delayed and stalled jobs are "
            "handled by the Worker itself in bullmq 6) before bumping again."
        ),
        log_fragments=(
            "TypeError: bullmq_1.QueueScheduler is not a constructor",
            "queues/scheduler.js:14:19",
            "Deployment crashed: container failed to start after 3 attempts",
        ),
        diff_quote='+    "bullmq": "^6.0.1",',
        deploy_quote="Build finished normally; the failure is at container start.",
    ),
    "timeout": Diagnosis(
        summary="storefront-api never became healthy: cache warm-up blocks startup",
        likely_cause=(
            "Commit {short} added `await warmProductCache()` before `app.listen` in "
            "apps/api/src/server.ts. The warm-up makes one HTTP call per product for 48,213 "
            "products; after five minutes it had finished about 7,000. The server does not "
            "listen until it is done, so every healthcheck got no response and Railway gave up "
            "after 300 seconds."
        ),
        suggested_fix=(
            "Start listening first and warm the cache in the background (drop the await, or "
            "move the call after app.listen). Batching the review lookups would also cut the "
            "warm-up time."
        ),
        log_fragments=(
            '"msg":"warming product cache","products":48213',
            "Healthcheck timed out after 300s",
            '"msg":"warming product cache","done":7150',
        ),
        diff_quote="+  await warmProductCache();",
        deploy_quote="No crash: the container ran for 300s without ever opening its port.",
        confidence="medium",
    ),
}

#: Commit message of the failing deploy → its diagnosis. That is how a run recognises a scenario.
DIAGNOSES: dict[str, Diagnosis] = {
    scenario.commit_message: _BY_SCENARIO[scenario.id] for scenario in (STRIPE_ENV, *SCENARIOS)
}
