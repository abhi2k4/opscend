"""Runtime settings, read from the environment and the repo-level `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = API_DIR.parent
# The documented local password. A deployment reachable from outside must change it.
DEFAULT_ADMIN_PASSWORD = "opscend-dev"


# OPSCEND_AI_PROVIDER → (default base URL, default model). Any other name is an
# OpenAI-compatible server at OPSCEND_AI_BASE_URL (vLLM, LocalAI, a gateway, ...).
# Self-hosted servers have no default model: it must be one the operator has loaded.
AI_PROVIDERS: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "ollama": ("http://localhost:11434/v1", ""),
    "lmstudio": ("http://localhost:1234/v1", ""),
    "llamacpp": ("http://localhost:8080/v1", ""),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", API_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field("sqlite+aiosqlite:///./opscend.db", alias="DATABASE_URL")
    redis_url: str | None = Field(None, alias="REDIS_URL")

    secret_key: str | None = Field(None, alias="OPSCEND_SECRET_KEY")
    admin_email: str = Field("admin@opscend.local", alias="OPSCEND_ADMIN_EMAIL")
    admin_password: str = Field(DEFAULT_ADMIN_PASSWORD, alias="OPSCEND_ADMIN_PASSWORD")
    session_hours: int = Field(24 * 7, alias="OPSCEND_SESSION_HOURS")
    cookie_secure: bool = Field(False, alias="OPSCEND_COOKIE_SECURE")

    demo: bool = Field(False, alias="OPSCEND_DEMO")
    # The public showcase: open to anyone without a login, sample data only, real
    # provider connections refused, and the model replaced by a scripted stand-in.
    public_demo: bool = Field(False, alias="OPSCEND_PUBLIC_DEMO")
    # Minutes after which the public demo's sample data is rebuilt (0 = never).
    public_demo_refresh_minutes: int = Field(120, alias="OPSCEND_PUBLIC_DEMO_REFRESH_MINUTES")
    # Each visitor explores a private copy. It is deleted after this many idle minutes,
    # and the least recently used one goes when there are more than the maximum.
    public_demo_session_minutes: int = Field(120, alias="OPSCEND_PUBLIC_DEMO_SESSION_MINUTES")
    public_demo_max_sessions: int = Field(300, alias="OPSCEND_PUBLIC_DEMO_MAX_SESSIONS")
    # Answer investigations and chat from a script instead of a model (see demo/simulated.py).
    ai_simulated_flag: bool = Field(False, alias="OPSCEND_AI_SIMULATED")
    simulated_delay_seconds: float = Field(0.9, alias="OPSCEND_AI_SIMULATED_DELAY")
    demo_webhook_secret: str = Field("opscend-demo-webhook", alias="OPSCEND_DEMO_WEBHOOK_SECRET")
    auto_migrate: bool = Field(True, alias="OPSCEND_AUTO_MIGRATE")
    # Without Redis the API process runs the periodic poll/health jobs itself; 0 turns that off.
    background_jobs: bool = Field(True, alias="OPSCEND_BACKGROUND_JOBS")

    # The model: Groq (hosted, needs GROQ_API_KEY) or a server you run yourself (Ollama,
    # LM Studio, llama.cpp, vLLM, ...), all through the OpenAI-compatible chat API.
    ai_provider: str = Field("groq", alias="OPSCEND_AI_PROVIDER")
    groq_api_key: str | None = Field(None, alias="GROQ_API_KEY")
    # Bearer token for any other endpoint; most self-hosted servers need none.
    ai_api_key: str | None = Field(None, alias="OPSCEND_AI_API_KEY")
    # Empty = the provider's default (see AI_PROVIDERS).
    ai_model: str = Field("", alias="OPSCEND_AI_MODEL")
    ai_base_url: str = Field("", alias="OPSCEND_AI_BASE_URL")
    # 0 = the default: 60s and 1000 tokens hosted, 300s and 4000 tokens self-hosted
    # (local models are slower, and "thinking" ones spend output tokens on reasoning).
    ai_timeout_seconds: float = Field(0, alias="OPSCEND_AI_TIMEOUT_SECONDS")
    ai_max_output_tokens: int = Field(0, alias="OPSCEND_AI_MAX_OUTPUT_TOKENS")
    ai_max_tool_calls: int = Field(8, alias="OPSCEND_AI_MAX_TOOL_CALLS")
    ai_token_budget: int = Field(40_000, alias="OPSCEND_AI_TOKEN_BUDGET")
    # Investigate a failed deploy as soon as its incident opens, up to a daily cap.
    auto_investigate: bool = Field(True, alias="OPSCEND_AUTO_INVESTIGATE")
    auto_investigate_daily_limit: int = Field(20, alias="OPSCEND_AUTO_INVESTIGATE_DAILY_LIMIT")

    # Email alerts. Leave OPSCEND_SMTP_HOST empty to keep notifications in-app only.
    smtp_host: str | None = Field(None, alias="OPSCEND_SMTP_HOST")
    smtp_port: int = Field(587, alias="OPSCEND_SMTP_PORT")
    smtp_username: str | None = Field(None, alias="OPSCEND_SMTP_USERNAME")
    smtp_password: str | None = Field(None, alias="OPSCEND_SMTP_PASSWORD")
    smtp_security: str = Field("starttls", alias="OPSCEND_SMTP_SECURITY")  # starttls | ssl | none
    email_from: str | None = Field(None, alias="OPSCEND_EMAIL_FROM")
    email_to: str | None = Field(None, alias="OPSCEND_EMAIL_TO")
    email_events: str = Field(
        "incident_opened,investigation_completed,integration_error", alias="OPSCEND_EMAIL_EVENTS"
    )
    # Base URL of the console, used for links in emails.
    public_url: str = Field("http://localhost:3000", alias="OPSCEND_PUBLIC_URL")

    poll_interval_seconds: int = Field(60, alias="OPSCEND_POLL_INTERVAL_SECONDS")
    health_interval_seconds: int = Field(60, alias="OPSCEND_HEALTH_INTERVAL_SECONDS")
    # Stored log lines and health checks older than this are deleted hourly; 0 keeps everything.
    retention_days: int = Field(30, alias="OPSCEND_RETENTION_DAYS")

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, url: str) -> str:
        """Accept the plain Postgres URL hosting providers hand out.

        Railway, Neon and friends give `postgres://` or `postgresql://`; the app needs
        the asyncpg driver, which also spells the TLS option `ssl`, not `sslmode`.
        """
        for scheme in ("postgres://", "postgresql://"):
            if url.startswith(scheme):
                url = "postgresql+asyncpg://" + url[len(scheme) :]
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("sslmode=", "ssl=")
        return url

    @model_validator(mode="after")
    def _public_demo_implies_demo(self) -> "Settings":
        if self.public_demo:
            self.demo = True
        return self

    @model_validator(mode="after")
    def _ai_defaults(self) -> "Settings":
        self.ai_provider = self.ai_provider.strip().lower() or "groq"
        base_url, model = AI_PROVIDERS.get(self.ai_provider, ("", ""))
        self.ai_base_url = (self.ai_base_url.strip() or base_url).rstrip("/")
        self.ai_model = self.ai_model.strip() or model
        if self.ai_timeout_seconds <= 0:
            self.ai_timeout_seconds = 300.0 if self.ai_self_hosted else 60.0
        if self.ai_max_output_tokens <= 0:
            self.ai_max_output_tokens = 4000 if self.ai_self_hosted else 1000
        return self

    @property
    def ai_self_hosted(self) -> bool:
        """True for anything but Groq: a model server the operator runs, key optional."""
        return self.ai_provider != "groq"

    @property
    def ai_key(self) -> str | None:
        own = (self.ai_api_key or "").strip()
        return own or (self.groq_api_key or "").strip() or None

    @property
    def ai_missing(self) -> str | None:
        """What stops the model from being used, as an instruction; None when it is ready."""
        if self.ai_simulated:
            return None
        if not self.ai_self_hosted:
            if self.ai_key:
                return None
            return (
                "Set GROQ_API_KEY in .env (free key at https://console.groq.com/keys), or "
                "point Opscend at a model you run yourself with OPSCEND_AI_PROVIDER=ollama"
            )
        if not self.ai_base_url:
            return (
                f"Set OPSCEND_AI_BASE_URL in .env to the OpenAI-compatible endpoint of your "
                f"'{self.ai_provider}' model server (for example http://localhost:8000/v1)"
            )
        if not self.ai_model:
            return (
                "Set OPSCEND_AI_MODEL in .env to a tool-calling model your server has "
                "loaded (for example qwen3:8b on Ollama)"
            )
        return None

    @property
    def ai_simulated(self) -> bool:
        """The public demo never calls a real model, even when a key is present."""
        return self.public_demo or self.ai_simulated_flag

    @property
    def ai_configured(self) -> bool:
        """True when investigations and chat can run: a model is set up, or simulated."""
        return self.ai_missing is None

    @property
    def ai_model_name(self) -> str:
        return "simulated" if self.ai_simulated else self.ai_model

    @property
    def email_recipient(self) -> str | None:
        return (self.email_to or "").strip() or None

    @property
    def email_sender(self) -> str | None:
        return (self.email_from or self.smtp_username or "").strip() or None

    @property
    def email_configured(self) -> bool:
        return bool((self.smtp_host or "").strip() and self.email_sender and self.email_recipient)

    @property
    def email_event_set(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.email_events.split(",") if part.strip())

    @property
    def database_kind(self) -> str:
        return "postgresql" if self.database_url.startswith("postgresql") else "sqlite"

    @property
    def queue_kind(self) -> str:
        return "arq" if self.redis_url else "inline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
