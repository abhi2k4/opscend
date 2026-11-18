"""Build a live adapter for a stored integration (the one place tokens are decrypted)."""

from app.core.crypto import decrypt
from app.integrations.base import DeploymentRef, ProviderAdapter, ServiceRef
from app.integrations.registry import build_adapter
from app.models import Deployment, Integration, Service


def adapter_for(integration: Integration) -> ProviderAdapter:
    secret = integration.webhook_secret_encrypted
    return build_adapter(
        integration.provider,
        decrypt(integration.token_encrypted),
        integration.config,
        webhook_secret=decrypt(secret) if secret else None,
    )


def service_ref(service: Service) -> ServiceRef:
    return ServiceRef(
        external_id=service.external_id, name=service.name, repo=service.repo, meta=service.meta
    )


def deployment_ref(deployment: Deployment) -> DeploymentRef:
    return DeploymentRef(
        external_id=deployment.external_id, service=service_ref(deployment.service)
    )
