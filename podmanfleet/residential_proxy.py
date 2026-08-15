import ipaddress
from typing import Literal, Self

from async_lru import alru_cache
from geoip2.errors import GeoIP2Error
from geoip2.webservice import AsyncClient
from loguru import logger
from pydantic import BaseModel, model_validator

from podmanfleet.settings import BrowserSettings

_SKIP_IP_LABELS = frozenset({"localhost", "unknown"})


def should_skip_geolocation(ip: str) -> bool:
    """True for IPs that MaxMind cannot (and should not) geolocate.

    Mirrors Go's net.IP checks: IsPrivate / IsLoopback / IsLinkLocalUnicast /
    IsMulticast / IsUnspecified. Covers Fly 6PN (fdaa:…) via ULA is_private.
    """
    if not ip or ip in _SKIP_IP_LABELS:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    )


class GeoLocation(BaseModel):
    country: str | None = None
    subdivision: str | None = None
    city: str | None = None
    city_compacted: str | None = None
    postal_code: str | None = None

    @model_validator(mode="after")
    def _validate_and_normalize(self) -> Self:
        self.country = (str(self.country) if self.country else "").lower().strip()
        self.subdivision = (
            (str(self.subdivision) if self.subdivision else "").lower().strip().replace(" ", "_")
        )
        self.city = (str(self.city) if self.city else "").lower().strip().replace(" ", "_")
        self.postal_code = str(self.postal_code) if self.postal_code else None

        if not self.country or len(self.country) != 2 or not self.country.isalpha():
            raise ValueError(
                f"Invalid country code: '{self.country}'. Must be a 2-character ISO country code (e.g., 'us', 'uk')"
            )

        # Geolocation guard: drop fields that don't apply outside US instead of raising.
        if self.country != "us":
            self.subdivision = ""
            self.postal_code = None

        if self.city:
            self.city_compacted = (
                self.city.lower().replace("-", "").replace("_", "").replace(" ", "")
            )

        return self


@alru_cache
async def get_location(ip: str, account_id: int, license_key: str) -> "GeoLocation | None":
    if should_skip_geolocation(ip):
        return None

    async with AsyncClient(account_id, license_key) as client:
        try:
            response = await client.city(ip)
        except GeoIP2Error as e:
            logger.warning(f"MaxMind GeoIP2 error for {ip}: {e}")
            return None

    country = response.country.iso_code
    subdivision = response.subdivisions.most_specific.iso_code
    city = response.city.name
    postal_code = response.postal.code

    try:
        location = GeoLocation(
            country=country,
            subdivision=subdivision,
            city=city,
            postal_code=postal_code,
        )
    except ValueError:
        return None

    logger.info(f"MaxMind resolved {ip} -> country={location.country}")
    return location


class OxylabsProxyConfig:
    type_: Literal["oxylabs", "massive"] = "oxylabs"

    def __init__(self, location: GeoLocation, username: str, password: str) -> None:
        self.location = location
        self.username = username
        self.password = password

    def get_proxy_url(self, session_id: str) -> str:
        # Country-only targeting — larger pool, higher success rate than finer-grained.
        return (
            f"http://customer-{self.username}-cc-{(self.location.country or 'us').upper()}"
            f"-sessid-{session_id}-sesstime-1440:{self.password}@pr.oxylabs.io:7777"
        )


class MassiveProxyConfig:
    type_: Literal["oxylabs", "massive"] = "massive"

    def __init__(self, location: GeoLocation, username: str, password: str) -> None:
        self.location = location
        self.username = username
        self.password = password

    def get_proxy_url(self, session_id: str) -> str:
        # Country-only targeting — mirror flyfleet; broader pool.
        return (
            f"http://{self.username}-country-{self.location.country}"
            f"-session-{session_id}-sessionttl-240:{self.password}@network.joinmassive.com:65534"
        )


async def get_proxy_config(
    origin_ip: str | None,
    settings: BrowserSettings,
) -> "OxylabsProxyConfig | MassiveProxyConfig | None":
    if not origin_ip:
        logger.info("No origin IP provided — skipping proxy selection")
        return None

    if not settings.MAXMIND_ENABLED:
        logger.info(
            f"x-origin-ip={origin_ip} provided but MaxMind not configured — skipping proxy selection"
        )
        return None

    location = await get_location(
        origin_ip, settings.MAXMIND_ACCOUNT_ID, settings.MAXMIND_LICENSE_KEY
    )
    if not location:
        logger.info(f"Could not resolve location for {origin_ip} — skipping proxy selection")
        return None

    proxies: dict[Literal["oxylabs", "massive"], OxylabsProxyConfig | MassiveProxyConfig] = {}
    if settings.OXYLABS_PROXY_ENABLED:
        proxies["oxylabs"] = OxylabsProxyConfig(
            location, settings.OXYLABS_USERNAME, settings.OXYLABS_PASSWORD
        )
    if settings.MASSIVE_PROXY_ENABLED:
        proxies["massive"] = MassiveProxyConfig(
            location, settings.MASSIVE_PROXY_USERNAME, settings.MASSIVE_PROXY_PASSWORD
        )

    if not proxies:
        logger.warning("x-origin-ip provided but no proxy provider is configured")
        return None

    if settings.DEFAULT_PROXY_TYPE in proxies:
        selected = settings.DEFAULT_PROXY_TYPE
        reason = "default"
    else:
        selected = next(iter(proxies))
        reason = "fallback (default unavailable)"

    logger.info(f"Proxy selected: provider={selected} reason={reason} country={location.country}")
    return proxies[selected]
