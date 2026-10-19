from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Keys
    openrouter_api_key: str = ""
    langchain_api_key: str = ""

    # LangSmith
    langchain_tracing_v2: bool = True
    langchain_project: str = "multi-agent-code-review"

    # Database
    database_url: str = "postgresql+asyncpg://review_user:review_pass@localhost:5432/review_db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Agent settings
    max_cost_per_review_usd: float = 0.50
    max_concurrent_agents: int = 3
    agent_timeout_seconds: int = 60
        # LLM step (set LLM_ENABLED=false for a fully free deployment with no API key)
    llm_enabled: bool = True
    llm_model: str = "openai/gpt-4o-mini"
    llm_input_price_per_million: float = 0.15
    llm_output_price_per_million: float = 0.60

    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        """Accept a plain Neon/Postgres URL and make it asyncpg-compatible."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        parts = urlsplit(v)
        query = dict(parse_qsl(parts.query))
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode in ("require", "verify-ca", "verify-full") and "ssl" not in query:
            query["ssl"] = "require"
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
