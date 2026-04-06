from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    backend_port: int = 8747

    # Nudge engine tuning
    nudge_check_interval_minutes: int = 15  # base interval; adaptive logic overrides
    max_nudges_per_task_per_day: int = 4
    nudge_backoff_minutes: int = 45  # min gap between nudges for same task

    class Config:
        env_file = ".env"


settings = Settings()
