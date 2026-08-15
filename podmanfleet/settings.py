from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class BrowserSettings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")

    PORT: int = 8400

    CONTAINER_IMAGE: str = "ghcr.io/remotebrowser/chrome-live"
    CONTAINER_HOST: str = ""

    # Residential proxy (Massive or Oxylabs)
    MASSIVE_PROXY_USERNAME: str = ""
    MASSIVE_PROXY_PASSWORD: str = ""
    OXYLABS_USERNAME: str = ""
    OXYLABS_PASSWORD: str = ""
    DEFAULT_PROXY_TYPE: Literal["massive", "oxylabs"] = "oxylabs"

    # MaxMind GeoIP
    MAXMIND_ACCOUNT_ID: int = 0
    MAXMIND_LICENSE_KEY: str = ""

    @property
    def MASSIVE_PROXY_ENABLED(self) -> bool:
        return bool(self.MASSIVE_PROXY_USERNAME and self.MASSIVE_PROXY_PASSWORD)

    @property
    def OXYLABS_PROXY_ENABLED(self) -> bool:
        return bool(self.OXYLABS_USERNAME and self.OXYLABS_PASSWORD)

    @property
    def MAXMIND_ENABLED(self) -> bool:
        return bool(self.MAXMIND_ACCOUNT_ID and self.MAXMIND_LICENSE_KEY)
