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
    jwt_secret_key: str = ""  # REQUIRED — set via JWT_SECRET_KEY env var
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

    # ─── Phase 5: OAuth2/OIDC ────────────────────────────────────────────
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = ""
    oauth_redirect_base_url: str = "http://localhost:8000"

    # ─── Phase 5: Stripe Billing ─────────────────────────────────────────
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_per_task: str = ""

    # ─── Phase 5: Prompt Injection Classifier ────────────────────────────
    injection_classifier_enabled: bool = False  # Enable in production
    injection_classifier_model: str = "claude-haiku-4-5-20251001"

    # ─── Phase 5: Audit Log Retention ────────────────────────────────────
    audit_retention_days: int = 30

    # ─── Phase 5: Webhook Notifications ──────────────────────────────────
    webhook_max_retries: int = 3
    webhook_retry_backoff_base: int = 2

    # ─── Phase 5 Track B: QA Multi-Round Rework ─────────────────────────
    qa_max_rework_rounds: int = 2

    # ─── Phase 5 Track B: Scheduled Tasks ───────────────────────────────
    scheduler_check_interval_seconds: int = 60

    # ─── Phase 5 Track B: Provider Health Monitoring ────────────────────
    provider_health_window_minutes: int = 15

    # ─── Phase 5 Track B: Per-Agent Cost Alerts ─────────────────────────
    agent_cost_alert_default_limit_usd: float = 2.0

    # ─── Phase 5 Track A: SOPS Secrets Management ─────────────────────
    sops_secrets_dir: str = ""  # Path to directory with SOPS-encrypted files
    sops_age_key_file: str = ""  # Path to AGE private key for decryption

    # ─── Phase 5 Track B: Fine-Tuning Pipeline ────────────────────────
    finetune_output_dir: str = "/tmp/nexus-finetune"
    finetune_min_eval_score: float = 0.7
    finetune_max_samples: int = 500

    # ─── Phase 5 Track C: OpenTelemetry ───────────────────────────────
    otel_exporter_endpoint: str = ""  # e.g. http://localhost:4318/v1/traces
    otel_service_name: str = "nexus-backend"

    # ─── Phase 5 Track C: Plugin System ───────────────────────────────
    plugin_auto_load: bool = True  # Load plugins from DB on startup

    # ─── Phase 6: Tool Safety ───────────────────────────────────────
    tool_file_read_max_bytes: int = 10 * 1024 * 1024  # 10MB
    tool_allowed_dirs: str = ""  # Comma-separated allowed directories for file_read

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


settings = Settings()
