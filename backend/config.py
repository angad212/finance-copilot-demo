from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://copilot:copilot@127.0.0.1:5433/copilot"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5-20251001"
    jwt_secret: str = "dev-only-change-me"
    jwt_expire_minutes: int = 480
    confidence_threshold: float = 0.7
    sql_row_limit: int = 200
    sql_echo: bool = False
    llm_retries: int = 2
    llm_backoff_seconds: float = 1.0


settings = Settings()
