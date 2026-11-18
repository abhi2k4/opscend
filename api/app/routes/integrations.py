"""Connecting provider accounts. Tokens go in, only `token_hint` ever comes out."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app import models, schemas
from app.core.crypto import encrypt, token_hint
from app.core.time import utcnow
from app.ingest import poller
from app.integrations import registry
from app.integrations.base import ProviderError
from app.integrations.connect import adapter_for

from .deps import SessionDep, get_or_404

router = APIRouter(prefix="/integrations", tags=["integrations"])

WEBHOOK_SECRET_FIELD = "webhook_secret"


def _out(integration: models.Integration) -> schemas.Integration:
    return schemas.Integration.model_validate(integration)


@router.get("/catalog")
async def catalog() -> list[schemas.ProviderManifest]:
    return registry.catalog()


@router.get("")
async def list_integrations(session: SessionDep) -> list[schemas.Integration]:
    rows = await session.scalars(select(models.Integration).order_by(models.Integration.created_at))
    return [_out(row) for row in rows.all()]


@router.post("", status_code=201)
async def create_integration(
    body: schemas.IntegrationCreate, session: SessionDep
) -> schemas.Integration:
    adapter_cls = registry.get_adapter_class(body.provider)
    if adapter_cls is None:
        raise HTTPException(400, f"Provider '{body.provider}' is not available yet")
    token = body.token.strip()
    config = {key: value for key, value in body.config.items() if value not in (None, "")}
    # The webhook secret arrives with the config form but is a secret: encrypt it separately.
    webhook_secret = config.pop(WEBHOOK_SECRET_FIELD, None)
    missing = [
        field.label
        for field in adapter_cls.manifest.config_fields
        if field.required and field.key not in config
    ]
    if missing:
        raise HTTPException(422, f"Missing required field(s): {', '.join(missing)}")

    adapter = adapter_cls(token, config)
    try:
        account = await adapter.validate()
    except ProviderError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await adapter.aclose()

    integration = models.Integration(
        provider=body.provider,
        account_name=account.account_name,
        token_encrypted=encrypt(token),
        token_hint=token_hint(token),
        webhook_secret_encrypted=encrypt(str(webhook_secret)) if webhook_secret else None,
        config=config,
        capabilities=sorted(adapter_cls.capabilities),
        status="connected",
    )
    session.add(integration)
    await session.commit()
    return await _sync(session, integration.id)


async def _sync(session: SessionDep, integration_id: str) -> schemas.Integration:
    await poller.sync_integration(integration_id)
    session.expire_all()
    return _out(await get_or_404(session, models.Integration, integration_id))


@router.post("/{integration_id}/test")
async def test_integration(integration_id: str, session: SessionDep) -> schemas.Integration:
    """Re-validate the stored token against the provider."""
    integration = await get_or_404(session, models.Integration, integration_id)
    if not integration.is_demo:
        adapter = adapter_for(integration)
        try:
            account = await adapter.validate()
            integration.account_name = account.account_name
            integration.status, integration.status_detail = "connected", None
        except ProviderError as exc:
            integration.status, integration.status_detail = "error", str(exc)
        finally:
            await adapter.aclose()
    else:
        integration.last_synced_at = utcnow()
    await session.commit()
    return _out(integration)


@router.post("/{integration_id}/sync")
async def sync_integration(integration_id: str, session: SessionDep) -> schemas.Integration:
    await get_or_404(session, models.Integration, integration_id)
    return await _sync(session, integration_id)


@router.delete("/{integration_id}")
async def delete_integration(integration_id: str, session: SessionDep) -> schemas.Ok:
    """Disconnect an account. Its services, deployments and incidents go with it."""
    integration = await get_or_404(session, models.Integration, integration_id)
    await session.delete(integration)
    await session.commit()
    return schemas.Ok()
