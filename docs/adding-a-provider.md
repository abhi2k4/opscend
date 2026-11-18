# Adding a provider

A provider is **one file plus one registry line**. Nothing else in the API needs to know
about it: routes, the poller, the webhook endpoint, the investigator and the UI all work
from the adapter's `capabilities` and `manifest`.

## 1. Write `api/app/integrations/<provider>.py`

Implement the `ProviderAdapter` protocol from `integrations/base.py`. Subclass `HttpAdapter`
to get the token, config and a shared `httpx` client for free.

```python
@register
class RenderAdapter(HttpAdapter):
    provider = "render"
    capabilities = frozenset({Capability.LIST_SERVICES, Capability.LIST_DEPLOYS,
                              Capability.BUILD_LOGS, Capability.WEBHOOKS})
    manifest = ProviderManifest(
        provider="render", name="Render", description="…", availability="available",
        capabilities=sorted(capabilities), token_label="API key",
        token_help_url="https://dashboard.render.com/u/settings#api-keys",
        config_fields=[ConfigField(key="webhook_secret", label="Webhook secret",
                                   required=False, placeholder="stored encrypted")],
        webhook_path="/api/webhooks/render",
    )

    async def validate(self) -> AccountInfo: ...             # cheap "who am I" call
    async def list_services(self) -> list[ServiceIn]: ...
    async def list_deployments(self, service: ServiceRef, since: datetime) -> list[DeploymentIn]: ...
    async def get_logs(self, deployment: DeploymentRef, kind: LogKind, limit: int = 500) -> list[LogLineIn]: ...
    def parse_webhook(self, headers: dict[str, str], body: bytes) -> list[RawEventIn]: ...
    @staticmethod
    def normalize(event_type: str, payload: dict) -> NormalizedBatch: ...
```

What each method owes the rest of the system:

| Method | Contract |
| --- | --- |
| `validate` | Raise `ProviderError` (message safe to show, never containing the token) if the token is bad. |
| `list_services` | Stable `external_id` per service. Put anything you need again later (project id, …) in `meta`. |
| `list_deployments` | Map provider states onto `queued / building / ready / failed / canceled`. Only return deploys started after `since`. |
| `get_logs` | Return `[]` for a kind you do not support, and leave that capability out. |
| `parse_webhook` | **Verify first** (HMAC or shared secret, constant-time compare) and raise `WebhookVerificationError` on mismatch. Return `RawEventIn`s with a `dedup_key` that is identical for a redelivery of the same event. |
| `normalize` | Pure function from a stored payload to `NormalizedBatch`. No network, no token. Return an empty batch for events you do not care about. |

Rules that keep the system honest:

- Only declare a capability you implement. The UI hides log tabs, webhook setup and so on
  based on it, and the poller only calls what is declared.
- Never log the token and never put it in an exception message. `HttpAdapter.__repr__`
  already hides it.
- A config field with the key `webhook_secret` is stored encrypted, not in `config`.
- A source-control provider (commits and diffs rather than deploys) additionally implements
  the small `CommitSource` protocol, as `github.py` does.

## 2. Register it

Add the module to `ADAPTER_MODULES` in `api/app/integrations/registry.py`:

```python
ADAPTER_MODULES = (
    "app.integrations.vercel",
    "app.integrations.railway",
    "app.integrations.github",
    "app.integrations.render",   # ← the one line
)
```

If the provider was listed in `PLANNED` in the same file, delete that placeholder.
`GET /api/integrations/catalog` now returns the real manifest and the UI can connect it.

## 3. Test it with fixtures

Save real API responses (secrets scrubbed) in `api/tests/fixtures/` and add tests next to
the existing ones in `api/tests/test_adapters.py`: state mapping, log parsing, webhook
signature accept/reject, and `normalize`. Mock HTTP with `respx`; the test suite refuses
any request that is not mocked, so a test can never hit the live API.

```
make check
```

## How the pieces use your adapter

```
webhook  → parse_webhook → raw_event (dedup) ┐
poller   → list_services / list_deployments ─┴→ normalize → deployment / commit → incident rules
UI / AI  → get_logs (cached once a deploy has finished)
```
