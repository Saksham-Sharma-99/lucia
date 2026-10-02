import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://lucia:lucia@localhost:5433/lucia"
    test_database_url: str = "postgresql+asyncpg://lucia:lucia@localhost:5433/lucia_test"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Fernet key (urlsafe base64, 32 bytes); also seeds the signer for consent links.
    secret_key: str = Field(min_length=40)
    session_ttl_days: int = 7
    session_cookie_name: str = "lucia_session"
    cookie_secure: bool = False
    public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"

    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_signing_secret: str = ""
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_pubsub_topic: str = ""
    google_pubsub_verification_token: str = ""
    vapi_api_key: str = ""
    vapi_webhook_secret: str = ""
    vapi_phone_number_id: str = ""  # used by firms that don't set their own number

    # Studio's AI drafter (wand + section drafts). Disabled while the key is empty.
    openai_api_key: str = ""
    drafter_model: str = "gpt-5.6-luna"

    allowed_models: Annotated[list[str], NoDecode] = ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-luna"]
    seed_password: str = ""

    @field_validator("allowed_models", mode="before")
    @classmethod
    def _parse_models(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value) if value.strip().startswith("[") else value.split(",")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
