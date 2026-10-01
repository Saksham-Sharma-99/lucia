from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://lucia:lucia@localhost:5433/lucia"
    test_database_url: str = "postgresql+asyncpg://lucia:lucia@localhost:5433/lucia_test"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
