from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from podmanfleet.settings import BrowserSettings

PROJECT_DIR = Path(__file__).resolve().parent.parent


class _Settings(BrowserSettings, BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env", env_ignore_empty=True, extra="ignore"
    )
    ENV: str = "local"
    GIT_REV: str = ""

    # Logging / OpenTelemetry
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_EXPORTER_OTLP_HEADERS: str = ""
    OTEL_SERVICE_NAME: str = "podman-fleet"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    SENTRY_DSN: str = ""

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()


settings = _Settings()
