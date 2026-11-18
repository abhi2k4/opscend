"""Runtime settings, read from the environment and the repo-level `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = API_DIR.parent


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
    admin_password: str = Field("opscend-dev", alias="OPSCEND_ADMIN_PASSWORD")
    session_hours: int = Field(24 * 7, alias="OPSCEND_SESSION_HOURS")
    cookie_secure: bool = Field(False, alias="OPSCEND_COOKIE_SECURE")

    demo: bool = Field(False, alias="OPSCEND_DEMO")
    demo_webhook_secret: str = Field("opscend-demo-webhook", alias="OPSCEND_DEMO_WEBHOOK_SECRET")
    auto_migrate: bool = Field(True, alias="OPSCEND_AUTO_MIGRATE")
    # Without Redis the API process runs the periodic poll/health jobs itself; 0 turns that off.
    background_jobs: bool = Field(True, alias="OPSCEND_BACKGROUND_JOBS")

    groq_api_key: str | None = Field(None, alias="GROQ_API_KEY")
    ai_provider: str = Field("groq", alias="OPSCEND_AI_PROVIDER")
    ai_model: str = Field("llama-3.3-70b-versatile", alias="OPSCEND_AI_MODEL")
    ai_base_url: str = Field("https://api.groq.com/openai/v1", alias="OPSCEND_AI_BASE_URL")
    ai_max_tool_calls: int = Field(8, alias="OPSCEND_AI_MAX_TOOL_CALLS")
    ai_token_budget: int = Field(40_000, alias="OPSCEND_AI_TOKEN_BUDGET")

    poll_interval_seconds: int = Field(60, alias="OPSCEND_POLL_INTERVAL_SECONDS")
    health_interval_seconds: int = Field(60, alias="OPSCEND_HEALTH_INTERVAL_SECONDS")

    @property
    def ai_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.strip())

    @property
    def database_kind(self) -> str:
        return "postgresql" if self.database_url.startswith("postgresql") else "sqlite"

    @property
    def queue_kind(self) -> str:
        return "arq" if self.redis_url else "inline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
