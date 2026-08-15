from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from podmanfleet.settings import BrowserSettings

PROJECT_DIR = Path(__file__).resolve().parent.parent


class _Settings(BrowserSettings, BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env", env_ignore_empty=True, extra="ignore"
    )
    ENVIRONMENT: str = "local"
    GIT_REV: str = ""

    # Logging / OpenTelemetry
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "podman-fleet"
    OTEL_LOG_LEVEL: str = "INFO"
    SENTRY_DSN: str = ""


settings = _Settings()
