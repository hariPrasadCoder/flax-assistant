import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    secret_key: str = Field(default_factory=lambda: os.urandom(32).hex())
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    backend_port: int = 8747

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""  # use the service role key for backend

    # Nudge engine tuning
    nudge_check_interval_minutes: int = 15  # base interval; adaptive logic overrides
    max_nudges_per_task_per_day: int = 4
    nudge_backoff_minutes: int = 45  # min gap between nudges for same task

    # Google Calendar OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Langfuse (optional — LLM observability)
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # LiteLLM — secondary model fallback
    litellm_fallback_model: str = "gemini/gemini-1.5-flash"

    # Sentry (error tracking)
    sentry_dsn: Optional[str] = None

    # App environment for tagging traces
    app_env: str = "development"

    # CORS — comma-separated origins, defaults to all for dev
    cors_origins: str = "*"

    # Rate limiting
    rate_limit_chat: str = "20/minute"  # per user

    class Config:
        env_file = ".env"


settings = Settings()
