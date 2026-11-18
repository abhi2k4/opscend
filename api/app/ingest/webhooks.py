"""Webhook intake: verify with the adapter, store raw events, nothing more."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import RawEventIn, WebhookVerificationError
from app.integrations.connect import adapter_for
from app.models import Integration, RawEvent
from app.schemas import Capability

from .store import record_event


class UnknownProviderError(Exception):
    """No connected integration of this provider accepts webhooks."""


async def receive_webhook(
    session: AsyncSession,
    provider: str,
    headers: dict[str, str],
    body: bytes,
    *,
    source: str = "webhook",
) -> list[RawEvent]:
    """Verify a delivery against each integration of the provider and store its events.

    Raises `UnknownProviderError` when nothing can receive it and
    `WebhookVerificationError` when no integration's secret verifies it.
    """
    integrations = (
        await session.scalars(select(Integration).where(Integration.provider == provider))
    ).all()
    candidates = [i for i in integrations if Capability.WEBHOOKS in i.capabilities]
    if not candidates:
        raise UnknownProviderError(provider)

    verified: tuple[list[RawEventIn], bool] | None = None
    for integration in candidates:
        try:
            verified = (adapter_for(integration).parse_webhook(headers, body), integration.is_demo)
            break
        except WebhookVerificationError:
            continue
        except (ValueError, KeyError, TypeError) as exc:
            raise WebhookVerificationError(f"malformed webhook body: {type(exc).__name__}") from exc
    if verified is None:
        raise WebhookVerificationError("signature did not match any connected integration")

    events, is_demo = verified
    return [
        row
        for event in events
        if (row := await record_event(session, event, source=source, is_demo=is_demo)) is not None
    ]
