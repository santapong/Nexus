from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables only."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus_dev@localhost:5432/nexus"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"

    # LLM API Keys — set the ones you need, leave others empty
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    mistral_api_key: str = ""

    # Local / custom model endpoints
    ollama_base_url: str = "http://localhost:11434/v1"
    openai_compat_base_url: str = "http://localhost:8080/v1"
    openai_compat_api_key: str = ""

    # Cost Controls
    daily_spend_limit_usd: Decimal = Decimal("5.00")
    default_token_budget_per_task: int = 50_000

    # Multi-tenant / Auth
    jwt_secret_key: str = "nexus-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours

    # Temporal
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "nexus"
    temporal_task_queue: str = "nexus-tasks"
    temporal_long_task_threshold_minutes: int = 30

    # LangFuse (eval tracking)
    langfuse_host: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # KeepSave Integration
    keepsave_url: str = ""
    keepsave_api_key: str = ""
    keepsave_project_id: str = ""
    nexus_env: str = "alpha"

    # Application
    app_env: str = "development"
    log_level: str = "INFO"
    cors_allowed_origins: str = "http://localhost:5173"

    # Database Pool (tunable for horizontal scaling)
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 3600
    db_pool_timeout: int = 30

    # Agent Model Map (role -> model name)
    model_ceo: str = "claude-sonnet-4-20250514"
    model_engineer: str = "claude-sonnet-4-20250514"
    model_analyst: str = "gemini-2.0-flash"
    model_writer: str = "claude-haiku-4-5-20251001"
    model_qa: str = "claude-haiku-4-5-20251001"
    model_prompt_creator: str = "claude-sonnet-4-20250514"

    # Fallback model chains per role (comma-separated, tried in order after primary fails)
    # Defaults to Groq llama — fast, free tier, good general coverage.
    # Set to "" to disable fallback for a role.
    model_ceo_fallbacks: str = "groq:llama-3.3-70b-versatile"
    model_engineer_fallbacks: str = "groq:llama-3.3-70b-versatile"
    model_analyst_fallbacks: str = "groq:llama-3.3-70b-versatile"
    model_writer_fallbacks: str = "groq:llama-3.3-70b-versatile"
    model_qa_fallbacks: str = "groq:llama-3.3-70b-versatile"
    model_prompt_creator_fallbacks: str = "groq:llama-3.3-70b-versatile"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()
