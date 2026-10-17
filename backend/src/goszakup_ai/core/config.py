from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: SecretStr
    api_database_url: SecretStr | None = None

    ows_token: SecretStr | None = None
    ows_base_url: str = "https://ows.goszakup.gov.kz"
    ows_timeout_sec: float = 60.0
    ows_max_concurrency: int = 4
    ows_rate_limit_per_sec: float = 5.0
    ows_max_attempts: int = 6
    ows_retry_base_delay_sec: float = 1.0

    ingest_concurrency: int = 4

    embedding_dir: Path = REPO_ROOT / "data" / "models"

    auth_secret: SecretStr | None = None
    auth_token_hours: float = 12.0

    llm_provider: Literal["openai", "qwen", "gemini"] = "openai"
    llm_fallback_provider: Literal["openai", "qwen", "gemini"] | None = None
    llm_temperature: float = 0.0
    llm_timeout_sec: float = 120.0
    llm_max_concurrency: int | None = None
    llm_requests_per_minute: int | None = None

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None

    qwen_api_key: SecretStr | None = None
    qwen_model: str = "qwen3-8"
    qwen_base_url: str = "https://llm.alem.ai/v1"

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
