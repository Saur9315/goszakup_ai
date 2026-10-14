from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr

    ows_token: SecretStr | None = None
    ows_base_url: str = "https://ows.goszakup.gov.kz"
    ows_timeout_sec: float = 60.0
    ows_max_concurrency: int = 4
    ows_rate_limit_per_sec: float = 5.0
    ows_max_attempts: int = 6
    ows_retry_base_delay_sec: float = 1.0

    ingest_concurrency: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
