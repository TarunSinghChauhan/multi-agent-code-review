from functools import lru_cache
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

    # GitHub
    github_token: str = ""
    github_webhook_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
