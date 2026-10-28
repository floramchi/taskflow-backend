from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://taskflow:taskflow@localhost:5432/taskflow"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60
    cache_ttl_seconds: int = 60
    overdue_scan_seconds: int = 60


settings = Settings()
