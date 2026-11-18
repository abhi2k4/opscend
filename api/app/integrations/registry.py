"""The provider registry.

Adapters register themselves with `@register`. Importing the adapter module is
what triggers that, so the only other step when adding a provider is one line in
`ADAPTER_MODULES` below. `PLANNED` holds manifest-only roadmap placeholders the
UI shows as "coming soon".
"""

from importlib import import_module
from typing import Any

from app.integrations.base import ProviderAdapter
from app.schemas import Capability, ProviderManifest

ADAPTER_MODULES = (
    "app.integrations.vercel",
    "app.integrations.railway",
    "app.integrations.github",
)

_adapters: dict[str, type[ProviderAdapter]] = {}
_loaded = False


def register[T: type](adapter_cls: T) -> T:
    """Class decorator: make an adapter available under its `provider` key."""
    _adapters[adapter_cls.provider] = adapter_cls
    return adapter_cls


def _load() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        for module in ADAPTER_MODULES:
            import_module(module)


def get_adapter_class(provider: str) -> type[ProviderAdapter] | None:
    _load()
    return _adapters.get(provider)


def build_adapter(
    provider: str,
    token: str,
    config: dict[str, Any] | None = None,
    *,
    webhook_secret: str | None = None,
) -> ProviderAdapter:
    adapter_cls = get_adapter_class(provider)
    if adapter_cls is None:
        raise KeyError(f"no adapter registered for provider '{provider}'")
    return adapter_cls(token, config, webhook_secret=webhook_secret)


def _planned(provider: str, name: str, description: str, *caps: Capability) -> ProviderManifest:
    return ProviderManifest(
        provider=provider,
        name=name,
        description=description,
        availability="planned",
        capabilities=sorted(caps),
        token_label="API token",
        token_help_url=None,
        config_fields=[],
        webhook_path=None,
    )


_DEPLOY = (Capability.LIST_SERVICES, Capability.LIST_DEPLOYS)

PLANNED: tuple[ProviderManifest, ...] = (
    _planned(
        "render",
        "Render",
        "Web services and deploys from the Render API.",
        *_DEPLOY,
        Capability.BUILD_LOGS,
        Capability.RUNTIME_LOGS,
        Capability.WEBHOOKS,
    ),
    _planned(
        "fly",
        "Fly.io",
        "Apps, releases and machine logs from Fly.io.",
        *_DEPLOY,
        Capability.RUNTIME_LOGS,
    ),
    _planned(
        "netlify",
        "Netlify",
        "Sites, deploys and build logs from Netlify.",
        *_DEPLOY,
        Capability.BUILD_LOGS,
        Capability.WEBHOOKS,
    ),
    _planned(
        "cloudflare",
        "Cloudflare",
        "Pages and Workers deployments from Cloudflare.",
        *_DEPLOY,
        Capability.BUILD_LOGS,
    ),
    _planned(
        "aws",
        "AWS",
        "ECS, Lambda and Amplify deployments with CloudWatch logs.",
        *_DEPLOY,
        Capability.RUNTIME_LOGS,
    ),
)


def catalog() -> list[ProviderManifest]:
    """Every provider the UI should list: registered adapters first, then the roadmap."""
    _load()

    def position(adapter: type[ProviderAdapter]) -> int:
        module = adapter.__module__
        return ADAPTER_MODULES.index(module) if module in ADAPTER_MODULES else len(ADAPTER_MODULES)

    available = sorted(_adapters.values(), key=position)
    return [adapter.manifest for adapter in available] + list(PLANNED)
