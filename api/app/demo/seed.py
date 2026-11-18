"""Demo data: a believable 48 hours of deploys for a fictional storefront.

Everything hangs off three integrations flagged `is_demo`, so a reset is one
cascading delete. All timestamps are relative to the moment of seeding.
"""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import encrypt, token_hint
from app.core.time import utcnow
from app.integrations.base import LogLineIn
from app.integrations.registry import get_adapter_class
from app.models import (
    Commit,
    CommitDiff,
    Deployment,
    HealthCheck,
    Incident,
    Integration,
    Investigation,
    InvestigationStep,
    LogLine,
    RawEvent,
    Service,
)
from app.services.logs import to_rows

from .scenarios import (
    RAILWAY_BUILD_OK,
    RAILWAY_RUNTIME_OK,
    STRIPE_ENV,
    VERCEL_BUILD_OK,
    LogSpec,
    Scenario,
)

REPO = "acme/storefront"
ACCOUNTS = {"vercel": "acme", "railway": "acme", "github": "acme-bot"}


@dataclass(frozen=True)
class ServiceSpec:
    key: str
    name: str
    provider: str
    external_id: str
    package: str
    directory: str
    health_url: str


SERVICES = (
    ServiceSpec(
        "web",
        "storefront-web",
        "vercel",
        "prj_8Kq2storefrontWebX4a1Zr9",
        "@acme/web",
        "apps/web",
        "https://storefront.acme.dev/",
    ),
    ServiceSpec(
        "api",
        "storefront-api",
        "railway",
        "5d0c7c1e-8f43-4b1e-9a57-2f6d1c0e8a11",
        "@acme/api",
        "apps/api",
        "https://storefront-api.up.railway.app/health",
    ),
    ServiceSpec(
        "worker",
        "worker",
        "railway",
        "b3a9e2f4-61d7-4c0a-8e52-7a4f9d3c1b60",
        "@acme/worker",
        "apps/worker",
        "https://storefront-worker.up.railway.app/healthz",
    ),
)
SERVICE_BY_NAME = {spec.name: spec for spec in SERVICES}

DANA, PRIYA, MARCUS = "Dana Okafor", "Priya Nair", "Marcus Lindqvist"

# (minutes ago, message, author, services, {service key: status other than ready})
HISTORY: tuple[tuple[int, str, str, str, dict[str, str]], ...] = (
    (2860, "chore: bump pnpm to 9.12", MARCUS, "web api worker", {}),
    (2740, "feat(catalog): faceted search filters", DANA, "web api worker", {}),
    (2610, "fix(cart): keep quantity when the variant changes", DANA, "web", {}),
    (2480, "feat(worker): retry failed fulfilment webhooks", PRIYA, "worker", {}),
    (2300, "refactor(api): move auth middleware into a package", MARCUS, "api worker", {}),
    (2150, "feat(checkout): Apple Pay button", DANA, "web api", {}),
    (1980, "fix(api): paginate order history", PRIYA, "api", {}),
    (1810, "feat(web): product image zoom", DANA, "web", {"web": "failed"}),
    (1785, "fix(web): import ImageZoom from the right path", DANA, "web", {}),
    (1620, "chore(deps): update next to 16.0.3", "dependabot[bot]", "web", {}),
    (1450, "feat(api): rate limit login attempts", MARCUS, "web api", {}),
    (1290, "fix(worker): dedupe order confirmation emails", PRIYA, "api worker", {}),
    (1100, "feat(search): typo tolerance", DANA, "web api", {}),
    (930, "docs: update the on-call runbook", MARCUS, "web", {"web": "canceled"}),
    (927, "feat(account): saved addresses", DANA, "web api", {}),
    (760, "fix(api): return 404 for an unknown sku", MARCUS, "api worker", {}),
    (600, "perf(web): lazy load the reviews widget", DANA, "web api", {}),
    (450, "feat(worker): nightly inventory sync", PRIYA, "api worker", {}),
    (300, "fix(checkout): round tax per line item", MARCUS, "web api", {}),
    (170, "chore(api): structured request logging", PRIYA, "api worker", {}),
    (95, "fix(web): hydrate the cart badge on first paint", DANA, "web api", {}),
    (38, STRIPE_ENV.commit_message, STRIPE_ENV.author, "web api", {"api": "failed"}),
    (3, "feat(worker): batch transactional emails", MARCUS, "worker", {"worker": "building"}),
)

IMAGE_ZOOM_FAILURE: tuple[LogSpec, ...] = (
    *VERCEL_BUILD_OK[:13],
    (31, "error", "Failed to compile."),
    (31, "error", "./app/products/[slug]/gallery.tsx:4:1"),
    (31, "error", "Module not found: Can't resolve '@/components/ImageZoom'"),
    (31, "error", '  2 | import Image from "next/image";'),
    (31, "error", '> 4 | import { ImageZoom } from "@/components/ImageZoom";'),
    (31, "error", "    | ^"),
    (31, "error", "https://nextjs.org/docs/messages/module-not-found"),
    (32, "error", "> Build failed because of Turbopack errors"),
    (32, "error", 'Error: Command "pnpm run build" exited with 1'),
)


def render_logs(
    specs: tuple[LogSpec, ...], start: datetime, sha: str, service: ServiceSpec
) -> list[LogLineIn]:
    """Materialize a log template for one deployment."""
    lines = []
    for offset, level, message in specs:
        text = (
            message.replace("{short}", sha[:7])
            .replace("{sha}", sha)
            .replace("{pkg}", service.package)
            .replace("{dir}", service.directory)
        )
        lines.append(LogLineIn(ts=start + timedelta(seconds=offset), level=level, message=text))
    return lines


def new_external_id(provider: str, rng: random.Random) -> str:
    if provider == "vercel":
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789"
        return "dpl_" + "".join(rng.choice(alphabet) for _ in range(28))
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def deployment_url(service: ServiceSpec, rng: random.Random) -> str:
    if service.provider == "vercel":
        slug = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(9))
        return f"https://{service.name}-{slug}-acme.vercel.app"
    return f"https://{service.name}-production.up.railway.app"


async def demo_exists(session: AsyncSession) -> bool:
    return await session.scalar(select(Integration.id).limit(1)) is not None


async def wipe_demo(session: AsyncSession) -> None:
    """Delete all demo data. Services, deploys, logs, incidents and investigations cascade."""
    await session.execute(delete(Integration).where(Integration.is_demo.is_(True)))
    for model in (Commit, CommitDiff, RawEvent):
        await session.execute(delete(model).where(model.is_demo.is_(True)))
    await session.commit()


async def seed_demo(session: AsyncSession) -> None:
    rng = random.Random(20261118)
    now = utcnow()
    settings = get_settings()

    services: dict[str, Service] = {}
    for provider, account in ACCOUNTS.items():
        token = f"demo-{provider}-token-{rng.getrandbits(32):08x}"
        integration = Integration(
            provider=provider,
            account_name=account,
            token_encrypted=encrypt(token),
            token_hint=token_hint(token),
            webhook_secret_encrypted=encrypt(settings.demo_webhook_secret),
            capabilities=sorted(get_adapter_class(provider).capabilities),
            status="connected",
            is_demo=True,
            last_synced_at=now,
            created_at=now - timedelta(days=3),
        )
        session.add(integration)
        await session.flush()
        for spec in SERVICES:
            if spec.provider == provider:
                services[spec.key] = Service(
                    integration_id=integration.id,
                    provider=provider,
                    external_id=spec.external_id,
                    name=spec.name,
                    repo=REPO,
                    health_url=spec.health_url,
                    meta={"project_id": "c1f0a6de-2b7c-4d3e-9f18-6e5a4b3c2d10"},
                    created_at=now - timedelta(days=3),
                )
                session.add(services[spec.key])
    await session.flush()

    by_key = {spec.key: spec for spec in SERVICES}
    deployments: dict[tuple[int, str], Deployment] = {}
    shas: dict[int, str] = {}
    for minutes, message, author, targets, overrides in HISTORY:
        sha = f"{rng.getrandbits(160):040x}"
        shas[minutes] = sha
        pushed = now - timedelta(minutes=minutes)
        session.add(
            Commit(
                repo=REPO,
                sha=sha,
                message=message,
                author=author,
                committed_at=pushed,
                url=f"https://github.com/{REPO}/commit/{sha}",
                is_demo=True,
            )
        )
        for key in targets.split():
            spec, status = by_key[key], overrides.get(key, "ready")
            started = pushed + timedelta(seconds=rng.randint(15, 45))
            build_logs, runtime_logs, seconds = _logs_for(spec, status, rng)
            if status == "failed" and key == "api":
                build_logs, runtime_logs = STRIPE_ENV.build_logs, STRIPE_ENV.runtime_logs
                seconds = STRIPE_ENV.build_seconds
            deployment = Deployment(
                service_id=services[key].id,
                provider=spec.provider,
                external_id=new_external_id(spec.provider, rng),
                status=status,
                commit_sha=sha,
                commit_message=message,
                commit_author=author,
                branch="main",
                environment="production",
                started_at=started,
                finished_at=None if status == "building" else started + timedelta(seconds=seconds),
                url=deployment_url(spec, rng) if status == "ready" else None,
            )
            deployment.service = services[key]
            session.add(deployment)
            await session.flush()
            deployments[(minutes, key)] = deployment
            session.add_all(
                to_rows(deployment.id, "build", render_logs(build_logs, started, sha, spec))
            )
            session.add_all(
                to_rows(deployment.id, "runtime", render_logs(runtime_logs, started, sha, spec))
            )

    for key, service in services.items():
        for index in range(24):
            blip = key == "api" and index == 6
            session.add(
                HealthCheck(
                    service_id=service.id,
                    status_code=503 if blip else 200,
                    latency_ms=rng.randint(900, 1400) if blip else rng.randint(60, 190),
                    ok=not blip,
                    checked_at=now - timedelta(seconds=20 + 60 * (23 - index)),
                )
            )

    broken_web, fixed_web = deployments[(1810, "web")], deployments[(1785, "web")]
    session.add(
        Incident(
            service_id=services["web"].id,
            trigger="deploy_failed",
            status="resolved",
            title=f"Deploy failed on storefront-web at {broken_web.commit_sha[:7]}",
            dedup_key=f"deploy:{broken_web.id}",
            deployment_id=broken_web.id,
            opened_at=broken_web.finished_at,
            resolved_at=fixed_web.finished_at,
        )
    )
    failed_api = deployments[(38, "api")]
    incident = Incident(
        service_id=services["api"].id,
        trigger="deploy_failed",
        status="open",
        title=f"Deploy failed on storefront-api at {failed_api.commit_sha[:7]}",
        dedup_key=f"deploy:{failed_api.id}",
        open_slot=services["api"].id,
        deployment_id=failed_api.id,
        opened_at=failed_api.finished_at,
    )
    session.add(incident)
    session.add(
        CommitDiff(
            repo=REPO,
            sha=failed_api.commit_sha,
            message=STRIPE_ENV.commit_message,
            author=STRIPE_ENV.author,
            files=[item.as_dict() for item in STRIPE_ENV.files],
            is_demo=True,
        )
    )
    await session.flush()
    await _seed_investigation(session, incident, failed_api, deployments[(38, "web")])
    await session.commit()


def _logs_for(
    spec: ServiceSpec, status: str, rng: random.Random
) -> tuple[tuple[LogSpec, ...], tuple[LogSpec, ...], int]:
    """Build logs, runtime logs and total duration for an ordinary demo deployment."""
    is_vercel = spec.provider == "vercel"
    build = VERCEL_BUILD_OK if is_vercel else RAILWAY_BUILD_OK
    build_seconds = int(build[-1][0])
    if status == "failed":
        return IMAGE_ZOOM_FAILURE, (), 33
    if status == "canceled":
        return (*build[:4], (6, "warn", "Build canceled: superseded by a newer commit")), (), 7
    if status == "building":
        return build[:9], (), 0
    if is_vercel:
        return build, (), build_seconds + rng.randint(2, 30)
    runtime = tuple((build_seconds + 4 + t, level, msg) for t, level, msg in RAILWAY_RUNTIME_OK)
    return build, runtime, build_seconds + 14 + rng.randint(5, 60)


async def _seed_investigation(
    session: AsyncSession, incident: Incident, failed: Deployment, healthy_web: Deployment
) -> None:
    """A finished investigation of the open incident, citing real seeded ids."""
    runtime = (
        await session.scalars(
            select(LogLine)
            .where(LogLine.deployment_id == failed.id, LogLine.kind == "runtime")
            .order_by(LogLine.seq)
        )
    ).all()

    def line(fragment: str) -> LogLine:
        return next(row for row in runtime if fragment in row.message)

    crash = line("Error: Missing required environment variable STRIPE_WEBHOOK_SECRET")
    frame = line("config/env.js:21:28")
    health = line("Healthcheck failed!")
    errors = sum(1 for row in runtime if row.level == "error")
    model = get_settings().ai_model
    sha = failed.commit_sha
    report = {
        "inconclusive": False,
        "summary": "storefront-api crashes at boot: STRIPE_WEBHOOK_SECRET is required but not set",
        "likely_cause": (
            f"Commit {sha[:7]} made STRIPE_WEBHOOK_SECRET a required environment variable in "
            "apps/api/src/config/env.ts, but the variable is not set on the Railway service. "
            "The build succeeded; the container then exited with code 1 on every start while "
            "loading config, so the healthcheck never passed and Railway marked the deploy failed."
        ),
        "confidence": "high",
        "culprit_commit_sha": sha,
        "evidence": [
            {"type": "log", "ref": crash.id, "deployment_id": failed.id, "quote": crash.message},
            {"type": "log", "ref": frame.id, "deployment_id": failed.id, "quote": frame.message},
            {"type": "log", "ref": health.id, "deployment_id": failed.id, "quote": health.message},
            {
                "type": "commit",
                "ref": sha,
                "quote": '+  STRIPE_WEBHOOK_SECRET: required("STRIPE_WEBHOOK_SECRET"),',
            },
            {
                "type": "deploy",
                "ref": failed.id,
                "quote": "Build finished normally; the failure is at container start.",
            },
            {
                "type": "deploy",
                "ref": healthy_web.id,
                "quote": "storefront-web deployed the same commit to Vercel without problems.",
            },
        ],
        "suggested_fix": (
            "Set STRIPE_WEBHOOK_SECRET (the whsec_… signing secret from the Stripe dashboard) in "
            "the storefront-api service variables on Railway and redeploy. To avoid a repeat, "
            "validate required variables in CI against the production variable list."
        ),
        "missing": None,
    }
    created = failed.finished_at + timedelta(minutes=4)
    steps = (
        ("llm", model, {"turn": 1, "forced_report": False}, "→ get_deployment, get_logs", 840, 742),
        (
            "tool",
            "get_deployment",
            {"deployment_id": failed.id},
            f"railway deployment of storefront-api, status failed, commit {sha[:7]} on main",
            12,
            None,
        ),
        (
            "tool",
            "get_logs",
            {"deployment_id": failed.id, "kind": "runtime"},
            f"runtime logs: showing {len(runtime)} of {len(runtime)}; {errors} error lines, "
            "repeated 'Missing required environment variable STRIPE_WEBHOOK_SECRET'",
            27,
            None,
        ),
        ("llm", model, {"turn": 2, "forced_report": False}, "→ get_commit_diff", 1310, 2864),
        (
            "tool",
            "get_commit_diff",
            {"sha": sha},
            f"commit {sha[:7]} in {REPO}, 3 file(s) changed: env.ts, stripe.ts, .env.example",
            9,
            None,
        ),
        ("llm", model, {"turn": 3, "forced_report": False}, "→ submit_report", 2180, 4127),
        (
            "report",
            "submit_report",
            {"confidence": "high", "culprit_commit_sha": sha, "evidence": 6},
            f"high confidence, 6 verified evidence ref(s): {report['summary']}",
            4,
            None,
        ),
    )
    investigation = Investigation(
        deployment_id=failed.id,
        incident_id=incident.id,
        service_name=failed.service.name,
        status="completed",
        model=model,
        report=report,
        tokens_used=sum(tokens or 0 for *_, tokens in steps),
        created_at=created,
    )
    session.add(investigation)
    await session.flush()
    clock = created + timedelta(milliseconds=180)
    for index, (type_, name, input_, summary, ms, tokens) in enumerate(steps):
        session.add(
            InvestigationStep(
                investigation_id=investigation.id,
                index=index,
                type=type_,
                name=name,
                input=input_,
                output_summary=summary,
                started_at=clock,
                duration_ms=ms,
                tokens=tokens,
                status="ok",
            )
        )
        clock += timedelta(milliseconds=ms + 15)
    investigation.finished_at = clock


async def seed_scenario_artifacts(
    session: AsyncSession, scenario: Scenario, deployment: Deployment, sha: str
) -> None:
    """Attach a scenario's logs and commit diff to the deployment the pipeline created."""
    spec = SERVICE_BY_NAME[scenario.service]
    end = deployment.finished_at or utcnow()
    for kind, specs in (("build", scenario.build_logs), ("runtime", scenario.runtime_logs)):
        lines = render_logs(specs, deployment.started_at, sha, spec)
        for line in lines:
            line.ts = min(line.ts, end)  # a shortened demo run must not log into the future
        session.add_all(to_rows(deployment.id, kind, lines))
    session.add(
        CommitDiff(
            repo=REPO,
            sha=sha,
            message=scenario.commit_message,
            author=scenario.author,
            files=[item.as_dict() for item in scenario.files],
            is_demo=True,
        )
    )
    await session.commit()
