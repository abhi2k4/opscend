"""The five scripted failures behind `POST /api/demo/break`, as plain data.

Log lines are `(seconds_after_start, level, message)`; `{sha}` / `{short}` are
replaced with the commit of the simulated push.
"""

from dataclasses import dataclass, field

LogSpec = tuple[float, str, str]


@dataclass(frozen=True)
class DiffFileSpec:
    filename: str
    patch: str
    status: str = "modified"

    @property
    def additions(self) -> int:
        return sum(1 for line in self.patch.splitlines() if line.startswith("+"))

    @property
    def deletions(self) -> int:
        return sum(1 for line in self.patch.splitlines() if line.startswith("-"))

    def as_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "patch": self.patch,
        }


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    description: str
    service: str  # demo service name the failing deploy lands on
    commit_message: str
    author: str
    files: tuple[DiffFileSpec, ...]
    build_logs: tuple[LogSpec, ...]
    runtime_logs: tuple[LogSpec, ...] = field(default=())
    build_seconds: int = 95


RAILWAY_BUILD_OK: tuple[LogSpec, ...] = (
    (0, "info", "==> Cloning acme/storefront at {short}"),
    (2, "info", "Using Nixpacks v1.38.0"),
    (2, "info", "setup      │ nodejs_22, pnpm-9_x"),
    (2, "info", "install    │ pnpm install --frozen-lockfile"),
    (2, "info", "build      │ pnpm --filter {pkg} build"),
    (2, "info", "start      │ node dist/server.js"),
    (
        4,
        "info",
        "#5 [stage-0  4/10] RUN nix-env -if .nixpacks/nixpkgs.nix && nix-collect-garbage -d",
    ),
    (4, "info", "#5 CACHED"),
    (6, "info", "#8 [stage-0  7/10] RUN pnpm install --frozen-lockfile"),
    (9, "info", "Lockfile is up to date, resolution step is skipped"),
    (21, "info", "Packages: +612"),
    (22, "info", "Done in 15.8s"),
    (23, "info", "#9 [stage-0  8/10] RUN pnpm --filter {pkg} build"),
    (24, "info", "> {pkg}@2.14.0 build /app/{dir}"),
    (24, "info", "> tsc -p tsconfig.build.json"),
    (48, "info", "#9 DONE 25.3s"),
    (50, "info", "#11 exporting to image"),
    (55, "info", "#11 writing image sha256:4be0c2a91d77 done"),
    (56, "info", "Build time: 56.21 seconds"),
    (58, "info", "==> Starting deployment, running healthcheck on /health"),
)

VERCEL_BUILD_OK: tuple[LogSpec, ...] = (
    (0, "info", "Running build in Washington, D.C., USA (East) – iad1"),
    (1, "info", "Cloning github.com/acme/storefront (Branch: main, Commit: {short})"),
    (2, "info", "Cloning completed: 1.204s"),
    (3, "info", "Restored build cache from previous deployment"),
    (4, "info", 'Running "vercel build"'),
    (5, "info", "Vercel CLI 48.2.1"),
    (6, "info", "Installing dependencies..."),
    (11, "info", "Lockfile is up to date, resolution step is skipped"),
    (14, "info", "Done in 8.4s"),
    (15, "info", "Detected Next.js version: 16.0.3"),
    (15, "info", 'Running "pnpm run build"'),
    (17, "info", "   ▲ Next.js 16.0.3 (Turbopack)"),
    (17, "info", "   Creating an optimized production build ..."),
    (39, "info", " ✓ Compiled successfully in 21.6s"),
    (40, "info", "   Linting and checking validity of types ..."),
    (52, "info", "   Collecting page data ..."),
    (58, "info", " ✓ Generating static pages (34/34)"),
    (60, "info", "   Finalizing page optimization ..."),
    (63, "info", "Build Completed in /vercel/output [48s]"),
    (64, "info", "Deploying outputs..."),
    (71, "info", "Deployment completed"),
    (72, "info", "Creating build cache..."),
)

RAILWAY_RUNTIME_OK: tuple[LogSpec, ...] = (
    (0, "info", "Starting Container"),
    (1, "info", "> node dist/server.js"),
    (2, "info", '{"level":"info","msg":"config loaded","env":"production"}'),
    (2, "info", '{"level":"info","msg":"postgres pool ready","max":10}'),
    (3, "info", '{"level":"info","msg":"redis connected"}'),
    (3, "info", '{"level":"info","msg":"listening","port":8080}'),
    (9, "info", '{"level":"info","msg":"GET /health 200","ms":3}'),
    (10, "info", "Healthcheck succeeded!"),
)

STRIPE_ENV = Scenario(
    id="seeded-stripe-secret",
    title="Missing STRIPE_WEBHOOK_SECRET",
    description="The seeded open incident: a new required env var was never set on Railway.",
    service="storefront-api",
    commit_message="feat(payments): verify Stripe webhook signatures",
    author="Priya Nair",
    files=(
        DiffFileSpec(
            "apps/api/src/config/env.ts",
            "@@ -14,6 +14,7 @@ export const env = {\n"
            '   DATABASE_URL: required("DATABASE_URL"),\n'
            '   REDIS_URL: required("REDIS_URL"),\n'
            '   STRIPE_SECRET_KEY: required("STRIPE_SECRET_KEY"),\n'
            '+  STRIPE_WEBHOOK_SECRET: required("STRIPE_WEBHOOK_SECRET"),\n'
            '   SENTRY_DSN: optional("SENTRY_DSN"),\n'
            " };\n",
        ),
        DiffFileSpec(
            "apps/api/src/routes/webhooks/stripe.ts",
            "@@ -1,12 +1,21 @@\n"
            ' import { Router } from "express";\n'
            '+import Stripe from "stripe";\n'
            '+import { env } from "../../config/env";\n'
            ' import { handleStripeEvent } from "../../payments/events";\n'
            " \n"
            " export const stripeWebhooks = Router();\n"
            "+const stripe = new Stripe(env.STRIPE_SECRET_KEY);\n"
            " \n"
            ' stripeWebhooks.post("/", async (req, res) => {\n'
            "-  const event = req.body;\n"
            '+  const signature = req.header("stripe-signature") ?? "";\n'
            "+  let event: Stripe.Event;\n"
            "+  try {\n"
            "+    event = stripe.webhooks.constructEvent(req.rawBody, signature, "
            "env.STRIPE_WEBHOOK_SECRET);\n"
            "+  } catch {\n"
            '+    return res.status(400).json({ error: "invalid signature" });\n'
            "+  }\n"
            "   await handleStripeEvent(event);\n"
            "   res.json({ received: true });\n"
            " });\n",
        ),
        DiffFileSpec(
            "apps/api/.env.example",
            "@@ -5,3 +5,4 @@ DATABASE_URL=postgres://localhost:5432/storefront\n"
            " REDIS_URL=redis://localhost:6379\n"
            " STRIPE_SECRET_KEY=sk_test_xxx\n"
            "+STRIPE_WEBHOOK_SECRET=whsec_xxx\n"
            " SENTRY_DSN=\n",
        ),
    ),
    build_logs=RAILWAY_BUILD_OK,
    runtime_logs=(
        (60, "info", "Starting Container"),
        (61, "info", "> @acme/api@2.14.0 start /app/apps/api"),
        (61, "info", "> node dist/server.js"),
        (62, "error", "/app/apps/api/dist/config/env.js:9"),
        (62, "error", "    throw new Error(`Missing required environment variable ${name}`);"),
        (62, "error", "          ^"),
        (62, "error", "Error: Missing required environment variable STRIPE_WEBHOOK_SECRET"),
        (62, "error", "    at required (/app/apps/api/dist/config/env.js:9:11)"),
        (62, "error", "    at Object.<anonymous> (/app/apps/api/dist/config/env.js:21:28)"),
        (62, "error", "    at Module._compile (node:internal/modules/cjs/loader:1730:14)"),
        (62, "error", "    at Object..js (node:internal/modules/cjs/loader:1895:10)"),
        (62, "error", "    at Module.load (node:internal/modules/cjs/loader:1465:32)"),
        (62, "error", "    at Function._load (node:internal/modules/cjs/loader:1282:12)"),
        (62, "error", "    at Module.require (node:internal/modules/cjs/loader:1487:12)"),
        (62, "error", "    at require (node:internal/modules/helpers:135:16)"),
        (
            62,
            "error",
            "    at Object.<anonymous> (/app/apps/api/dist/routes/webhooks/stripe.js:8:15)",
        ),
        (62, "error", "Node.js v22.11.0"),
        (63, "warn", "Container exited with code 1, restarting (attempt 1/3)"),
        (65, "info", "> node dist/server.js"),
        (66, "error", "Error: Missing required environment variable STRIPE_WEBHOOK_SECRET"),
        (66, "error", "    at required (/app/apps/api/dist/config/env.js:9:11)"),
        (67, "warn", "Container exited with code 1, restarting (attempt 2/3)"),
        (70, "info", "> node dist/server.js"),
        (71, "error", "Error: Missing required environment variable STRIPE_WEBHOOK_SECRET"),
        (71, "error", "    at required (/app/apps/api/dist/config/env.js:9:11)"),
        (72, "warn", "Container exited with code 1, restarting (attempt 3/3)"),
        (118, "warn", "Healthcheck attempt #4 failed with service unavailable. Retrying in 8s"),
        (160, "error", "1/1 replicas never became healthy!"),
        (
            160,
            "error",
            "Healthcheck failed! Deployment marked as FAILED, previous deploy stays live",
        ),
    ),
    build_seconds=160,
)

SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        id="bad-env-var",
        title="Bad environment variable",
        description="The API starts reading CACHE_URL instead of REDIS_URL, but nobody set it.",
        service="storefront-api",
        commit_message="refactor(cache): rename REDIS_URL to CACHE_URL",
        author="Marcus Lindqvist",
        files=(
            DiffFileSpec(
                "apps/api/src/config/env.ts",
                "@@ -13,7 +13,7 @@ export const env = {\n"
                '   PORT: Number(optional("PORT") ?? 8080),\n'
                '   DATABASE_URL: required("DATABASE_URL"),\n'
                '-  REDIS_URL: required("REDIS_URL"),\n'
                '+  CACHE_URL: required("CACHE_URL"),\n'
                '   STRIPE_SECRET_KEY: required("STRIPE_SECRET_KEY"),\n',
            ),
            DiffFileSpec(
                "apps/api/src/cache/client.ts",
                '@@ -2,5 +2,5 @@ import { createClient } from "redis";\n'
                ' import { env } from "../config/env";\n'
                " \n"
                "-export const cache = createClient({ url: env.REDIS_URL });\n"
                "+export const cache = createClient({ url: env.CACHE_URL });\n",
            ),
        ),
        build_logs=RAILWAY_BUILD_OK,
        runtime_logs=(
            (60, "info", "Starting Container"),
            (61, "info", "> node dist/server.js"),
            (62, "error", "/app/apps/api/dist/config/env.js:9"),
            (62, "error", "    throw new Error(`Missing required environment variable ${name}`);"),
            (62, "error", "Error: Missing required environment variable CACHE_URL"),
            (62, "error", "    at required (/app/apps/api/dist/config/env.js:9:11)"),
            (62, "error", "    at Object.<anonymous> (/app/apps/api/dist/config/env.js:17:16)"),
            (62, "error", "    at Module._compile (node:internal/modules/cjs/loader:1730:14)"),
            (62, "error", "    at Object.<anonymous> (/app/apps/api/dist/cache/client.js:5:15)"),
            (62, "error", "Node.js v22.11.0"),
            (63, "warn", "Container exited with code 1, restarting (attempt 1/3)"),
            (66, "error", "Error: Missing required environment variable CACHE_URL"),
            (67, "warn", "Container exited with code 1, restarting (attempt 2/3)"),
            (71, "error", "Error: Missing required environment variable CACHE_URL"),
            (
                90,
                "error",
                "Healthcheck failed! Deployment marked as FAILED, previous deploy stays live",
            ),
        ),
    ),
    Scenario(
        id="syntax-error",
        title="Syntax error",
        description="A half-finished edit to the checkout page breaks the Next.js build on Vercel.",
        service="storefront-web",
        commit_message="feat(checkout): show estimated delivery date",
        author="Dana Okafor",
        files=(
            DiffFileSpec(
                "apps/web/app/checkout/summary.tsx",
                "@@ -18,9 +18,12 @@ export function OrderSummary({ cart }: Props) {\n"
                "   return (\n"
                '     <section className="summary">\n'
                "       <Totals cart={cart} />\n"
                "+      {cart.eta && (\n"
                '+        <p className="eta">Arrives by {formatDate(cart.eta)}\n'
                "+      )}\n"
                "       <PayButton cart={cart} />\n"
                "     </section>\n"
                "   );\n",
            ),
        ),
        build_logs=(
            *VERCEL_BUILD_OK[:13],
            (24, "error", "Failed to compile."),
            (24, "error", "./app/checkout/summary.tsx:23:8"),
            (24, "error", "Parsing ecmascript source code failed"),
            (24, "error", "  21 |       {cart.eta && ("),
            (24, "error", '  22 |         <p className="eta">Arrives by {formatDate(cart.eta)}'),
            (24, "error", "> 23 |       )}"),
            (24, "error", "     |        ^"),
            (24, "error", "  24 |       <PayButton cart={cart} />"),
            (24, "error", "Unexpected token. Did you mean `{'}'}` or `&rbrace;`?"),
            (24, "error", "Expected corresponding JSX closing tag for <p>"),
            (25, "error", "Import trace for requested module:"),
            (25, "error", "./app/checkout/summary.tsx"),
            (25, "error", "./app/checkout/page.tsx"),
            (25, "error", "> Build failed because of Turbopack errors"),
            (26, "error", " ELIFECYCLE  Command failed with exit code 1."),
            (26, "error", 'Error: Command "pnpm run build" exited with 1'),
        ),
        build_seconds=27,
    ),
    Scenario(
        id="failing-migration",
        title="Failing migration",
        description="The release step runs a migration that indexes a column that does not exist.",
        service="storefront-api",
        commit_message="perf(orders): index orders by customer and created_at",
        author="Priya Nair",
        files=(
            DiffFileSpec(
                "apps/api/migrations/20261118093000_orders_customer_idx.sql",
                "@@ -0,0 +1,3 @@\n"
                "+-- speeds up the account order history page\n"
                "+CREATE INDEX CONCURRENTLY orders_customer_created_idx\n"
                "+  ON orders (customer_id, created_at DESC);\n",
                status="added",
            ),
            DiffFileSpec(
                "apps/api/src/orders/repository.ts",
                "@@ -31,7 +31,7 @@ export async function listForCustomer(id: string) {\n"
                "   return db\n"
                '     .selectFrom("orders")\n'
                '-    .where("user_id", "=", id)\n'
                '+    .where("customer_id", "=", id)\n'
                '     .orderBy("created_at", "desc")\n',
            ),
        ),
        build_logs=(
            *RAILWAY_BUILD_OK[:19],
            (58, "info", "==> Running pre-deploy command: pnpm --filter @acme/api migrate"),
            (60, "info", "> @acme/api@2.14.0 migrate /app/apps/api"),
            (60, "info", "> node dist/scripts/migrate.js"),
            (61, "info", "migrate: 41 applied, 1 pending"),
            (61, "info", "migrate: applying 20261118093000_orders_customer_idx.sql"),
            (62, "error", 'error: column "customer_id" does not exist'),
            (62, "error", "    at /app/node_modules/pg/lib/client.js:545:17"),
            (
                62,
                "error",
                "    at async applyMigration (/app/apps/api/dist/scripts/migrate.js:48:5)",
            ),
            (62, "error", "    at async main (/app/apps/api/dist/scripts/migrate.js:71:7) {"),
            (62, "error", "  severity: 'ERROR', code: '42703', routine: 'ComputeIndexAttrs'"),
            (62, "error", "}"),
            (62, "error", "migrate: FAILED 20261118093000_orders_customer_idx.sql, rolled back"),
            (63, "error", " ELIFECYCLE  Command failed with exit code 1."),
            (63, "error", "Pre-deploy command failed with exit code 1. Deployment aborted"),
        ),
        build_seconds=64,
    ),
    Scenario(
        id="dependency-bump",
        title="Dependency bump",
        description="A major bump of the queue library removes an API the worker still calls.",
        service="worker",
        commit_message="chore(deps): bump bullmq from 4.17.0 to 6.0.1",
        author="dependabot[bot]",
        files=(
            DiffFileSpec(
                "apps/worker/package.json",
                '@@ -12,7 +12,7 @@\n   "dependencies": {\n'
                '     "@acme/db": "workspace:*",\n'
                '-    "bullmq": "^4.17.0",\n'
                '+    "bullmq": "^6.0.1",\n'
                '     "ioredis": "^5.4.1",\n',
            ),
            DiffFileSpec(
                "pnpm-lock.yaml",
                "@@ -3310,8 +3310,8 @@ packages:\n"
                "-  bullmq@4.17.0:\n"
                "-    resolution: {integrity: sha512-9k2c...}\n"
                "+  bullmq@6.0.1:\n"
                "+    resolution: {integrity: sha512-Qm1x...}\n",
            ),
        ),
        build_logs=tuple(
            (t, lvl, msg.replace("{pkg}", "@acme/worker").replace("{dir}", "apps/worker"))
            for t, lvl, msg in RAILWAY_BUILD_OK
        ),
        runtime_logs=(
            (60, "info", "Starting Container"),
            (61, "info", "> node dist/main.js"),
            (62, "info", '{"level":"info","msg":"worker booting","queues":["email","fulfilment"]}'),
            (62, "error", "/app/apps/worker/dist/queues/scheduler.js:14"),
            (62, "error", "const scheduler = new bullmq_1.QueueScheduler(name, { connection });"),
            (62, "error", "                  ^"),
            (62, "error", "TypeError: bullmq_1.QueueScheduler is not a constructor"),
            (
                62,
                "error",
                "    at createScheduler (/app/apps/worker/dist/queues/scheduler.js:14:19)",
            ),
            (62, "error", "    at Array.map (<anonymous>)"),
            (62, "error", "    at Object.<anonymous> (/app/apps/worker/dist/main.js:22:31)"),
            (62, "error", "    at Module._compile (node:internal/modules/cjs/loader:1730:14)"),
            (62, "error", "Node.js v22.11.0"),
            (63, "warn", "Container exited with code 1, restarting (attempt 1/3)"),
            (66, "error", "TypeError: bullmq_1.QueueScheduler is not a constructor"),
            (67, "warn", "Container exited with code 1, restarting (attempt 2/3)"),
            (71, "error", "TypeError: bullmq_1.QueueScheduler is not a constructor"),
            (88, "error", "Deployment crashed: container failed to start after 3 attempts"),
        ),
    ),
    Scenario(
        id="timeout",
        title="Startup timeout",
        description="A new cache warm-up blocks startup until the platform healthcheck gives up.",
        service="storefront-api",
        commit_message="perf(catalog): warm product cache before accepting traffic",
        author="Marcus Lindqvist",
        files=(
            DiffFileSpec(
                "apps/api/src/server.ts",
                '@@ -8,6 +8,8 @@ import { env } from "./config/env";\n'
                " async function main() {\n"
                "   await db.connect();\n"
                "   await cache.connect();\n"
                "+  // make the first request fast\n"
                "+  await warmProductCache();\n"
                '   app.listen(env.PORT, () => log.info({ port: env.PORT }, "listening"));\n'
                " }\n",
            ),
            DiffFileSpec(
                "apps/api/src/catalog/warm.ts",
                "@@ -0,0 +1,11 @@\n"
                '+import { db } from "../db";\n'
                '+import { cache } from "../cache/client";\n'
                "+\n"
                "+export async function warmProductCache() {\n"
                '+  const products = await db.selectFrom("products").selectAll().execute();\n'
                "+  for (const product of products) {\n"
                "+    const reviews = await fetchReviews(product.id); // one HTTP call per product\n"
                "+    await cache.set(`product:${product.id}`, JSON.stringify({ product, reviews }));\n"
                "+  }\n"
                "+}\n",
                status="added",
            ),
        ),
        build_logs=RAILWAY_BUILD_OK,
        runtime_logs=(
            (60, "info", "Starting Container"),
            (61, "info", "> node dist/server.js"),
            (62, "info", '{"level":"info","msg":"config loaded","env":"production"}'),
            (62, "info", '{"level":"info","msg":"postgres pool ready","max":10}'),
            (63, "info", '{"level":"info","msg":"redis connected"}'),
            (63, "info", '{"level":"info","msg":"warming product cache","products":48213}'),
            (74, "warn", "Healthcheck attempt #1 failed with service unavailable. Retrying in 2s"),
            (93, "info", '{"level":"info","msg":"warming product cache","done":900,"total":48213}'),
            (98, "warn", "Healthcheck attempt #5 failed with service unavailable. Retrying in 8s"),
            (
                153,
                "info",
                '{"level":"info","msg":"warming product cache","done":2700,"total":48213}',
            ),
            (
                180,
                "warn",
                '{"level":"warn","msg":"reviews API slow","ms":2140,"product":"sku_8841"}',
            ),
            (
                240,
                "warn",
                "Healthcheck attempt #14 failed with service unavailable. Retrying in 30s",
            ),
            (
                300,
                "info",
                '{"level":"info","msg":"warming product cache","done":7150,"total":48213}',
            ),
            (360, "error", "Healthcheck timed out after 300s: no response on port 8080"),
            (360, "error", "1/1 replicas never became healthy!"),
            (
                361,
                "error",
                "Healthcheck failed! Deployment marked as FAILED, previous deploy stays live",
            ),
        ),
        build_seconds=361,
    ),
)

SCENARIOS_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}
