"""Shared fixtures: an isolated SQLite database per test and API clients."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.core import crypto, db
from app.core import queue as queue_module
from app.core.config import get_settings
from app.core.time import utcnow
from app.incidents import rules
from app.ingest import normalizer, poller
from app.models import Deployment, Integration, Service

FIXTURES = Path(__file__).parent / "fixtures"
ADMIN = {"email": "admin@opscend.local", "password": "opscend-dev"}
SECRET_TOKEN = "vercel-secret-token-do-not-leak-9z8y"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _clear_caches() -> None:
    get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.get_sessionmaker.cache_clear()
    crypto._fernet.cache_clear()


@pytest.fixture(autouse=True)
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the app at a fresh database and neutral settings, whatever .env says."""
    values = {
        "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        "REDIS_URL": "",
        "OPSCEND_SECRET_KEY": Fernet.generate_key().decode(),
        "OPSCEND_ADMIN_EMAIL": ADMIN["email"],
        "OPSCEND_ADMIN_PASSWORD": ADMIN["password"],
        "OPSCEND_DEMO": "0",
        "OPSCEND_DEMO_WEBHOOK_SECRET": "test-webhook-secret",
        "OPSCEND_BACKGROUND_JOBS": "0",
        "OPSCEND_AI_MODEL": "test-model",
        "GROQ_API_KEY": "",
        "OPSCEND_SMTP_HOST": "",
        "OPSCEND_EMAIL_FROM": "",
        "OPSCEND_EMAIL_TO": "",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    _clear_caches()
    normalizer._lock = asyncio.Lock()
    poller._reconciling = asyncio.Lock()
    # The recorded fixtures carry fixed timestamps, so "too old to be an incident" is
    # switched off here and tested on its own in test_incidents.py.
    monkeypatch.setattr(rules, "INCIDENT_MAX_AGE", timedelta(days=36500))
    yield monkeypatch
    _clear_caches()


@pytest.fixture(autouse=True)
def no_live_http():
    """Tests never touch the network: any request a test did not mock raises."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True):
        yield


@pytest.fixture
async def database(env) -> AsyncIterator[None]:
    """A migrated, empty database (for tests that do not need the HTTP app)."""
    await db.run_migrations()
    yield
    await db.get_engine().dispose()


@asynccontextmanager
async def running_app() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
async def anon_client(env) -> AsyncIterator[httpx.AsyncClient]:
    async with running_app() as client:
        yield client


@pytest.fixture
async def client(anon_client: httpx.AsyncClient) -> httpx.AsyncClient:
    """A logged-in client, demo mode off."""
    response = await anon_client.post("/api/auth/login", json=ADMIN)
    assert response.status_code == 200
    return anon_client


@pytest.fixture
async def demo_client(env) -> AsyncIterator[httpx.AsyncClient]:
    """A logged-in client with demo data seeded."""
    env.setenv("OPSCEND_DEMO", "1")
    _clear_caches()
    async with running_app() as client:
        assert (await client.post("/api/auth/login", json=ADMIN)).status_code == 200
        yield client


async def drain_jobs() -> None:
    await queue_module.get_queue().drain()


async def make_service(
    session,
    *,
    provider: str = "vercel",
    name: str = "storefront-web",
    external_id: str = "prj_QmT4wq1storefront",
    webhook_secret: str | None = "test-webhook-secret",
    token: str = SECRET_TOKEN,
    health_url: str | None = None,
) -> Service:
    """An integration (looked up by provider, created if missing) with one service."""
    from sqlalchemy import select

    from app.integrations.registry import get_adapter_class

    integration = await session.scalar(select(Integration).where(Integration.provider == provider))
    if integration is None:
        integration = Integration(
            provider=provider,
            account_name="acme",
            token_encrypted=crypto.encrypt(token),
            token_hint=crypto.token_hint(token),
            webhook_secret_encrypted=crypto.encrypt(webhook_secret) if webhook_secret else None,
            capabilities=sorted(get_adapter_class(provider).capabilities),
            status="connected",
        )
        session.add(integration)
        await session.flush()
    service = Service(
        integration_id=integration.id,
        provider=provider,
        external_id=external_id,
        name=name,
        repo="acme/storefront",
        health_url=health_url,
        meta={},
    )
    session.add(service)
    await session.commit()
    return service


async def make_deployment(
    session,
    service: Service,
    *,
    status: str = "ready",
    minutes_ago: float = 5,
    external_id: str | None = None,
    sha: str | None = "bb083918c9be1579a96112ac2a5779ee95256c89",
) -> Deployment:
    started = utcnow() - timedelta(minutes=minutes_ago)
    deployment = Deployment(
        service_id=service.id,
        provider=service.provider,
        external_id=external_id or f"ext-{minutes_ago}-{status}",
        status=status,
        commit_sha=sha,
        commit_message="feat(payments): verify Stripe webhook signatures",
        commit_author="Priya Nair",
        branch="main",
        environment="production",
        started_at=started,
        finished_at=None if status in ("queued", "building") else started + timedelta(seconds=90),
    )
    deployment.service = service
    session.add(deployment)
    await session.commit()
    return deployment
