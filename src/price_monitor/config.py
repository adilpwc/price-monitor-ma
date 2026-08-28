from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import ProductConfig


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HttpSettings:
    timeout_seconds: float
    user_agent: str
    max_results_per_site: int


@dataclass(frozen=True, slots=True)
class SiteSettings:
    name: str
    enabled: bool
    kind: str
    base_url: str
    search_path: str
    query_param: str
    card_selector: str
    title_selector: str
    price_selector: str
    link_selector: str
    image_selector: str | None = None
    availability_selector: str | None = None
    unavailable_text: tuple[str, ...] = ()
    product_url_include: tuple[str, ...] = ()
    product_url_exclude: tuple[str, ...] = ()

    def build_search_url(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.search_path.lstrip("/")


@dataclass(frozen=True, slots=True)
class AlertSettings:
    cooldown_hours: int
    notify_back_in_stock: bool


@dataclass(frozen=True, slots=True)
class Settings:
    timezone: ZoneInfo
    http: HttpSettings
    sites: tuple[SiteSettings, ...]
    alerts: AlertSettings


def _mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{context} doit être un objet YAML")
    return cast(dict[str, Any], value)


def _str(data: dict[str, Any], key: str, context: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{context}.{key} doit être une chaîne non vide")
    return value.strip()


def _bool(data: dict[str, Any], key: str, context: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{context}.{key} doit être un booléen YAML")
    return value


def _positive_number(data: dict[str, Any], key: str, context: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{context}.{key} doit être strictement positif")
    return float(value)


def _valid_url(value: str, context: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ConfigError(f"{context} doit être une URL HTTPS")
    return value.rstrip("/")


def load_settings(path: Path) -> Settings:
    raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "settings")
    timezone_name = _str(raw, "timezone", "settings", "Africa/Casablanca")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Fuseau inconnu: {timezone_name}") from exc

    http = _mapping(raw.get("http", {}), "http")
    http_settings = HttpSettings(
        timeout_seconds=_positive_number(http, "timeout_seconds", "http", 20),
        user_agent=_str(http, "user_agent", "http", "price-monitor-ma/2.0"),
        max_results_per_site=int(_positive_number(http, "max_results_per_site", "http", 10)),
    )

    sites_raw = _mapping(raw.get("sites"), "sites")
    sites: list[SiteSettings] = []
    for name, value in sites_raw.items():
        site = _mapping(value, f"sites.{name}")
        context = f"sites.{name}"
        kind = _str(site, "kind", context, "html")
        if kind not in {"html", "json"}:
            raise ConfigError(f"{context}.kind doit valoir html ou json")
        sites.append(
            SiteSettings(
                name=name,
                enabled=_bool(site, "enabled", context, True),
                kind=kind,
                base_url=_valid_url(_str(site, "base_url", context), f"{context}.base_url"),
                search_path=_str(site, "search_path", context),
                query_param=_str(site, "query_param", context, "q"),
                card_selector=_str(site, "card_selector", context, "article"),
                title_selector=_str(site, "title_selector", context, "h2"),
                price_selector=_str(site, "price_selector", context, "[itemprop='price']"),
                link_selector=_str(site, "link_selector", context, "a"),
                image_selector=site.get("image_selector"),
                availability_selector=site.get("availability_selector"),
                unavailable_text=tuple(
                    str(item).lower() for item in site.get("unavailable_text", [])
                ),
                product_url_include=tuple(
                    str(item).lower() for item in site.get("product_url_include", [])
                ),
                product_url_exclude=tuple(
                    str(item).lower() for item in site.get("product_url_exclude", [])
                ),
            )
        )
    if not any(site.enabled for site in sites):
        raise ConfigError("Au moins un site doit être activé")

    alerts = _mapping(raw.get("alerts", {}), "alerts")
    alert_settings = AlertSettings(
        cooldown_hours=int(_positive_number(alerts, "cooldown_hours", "alerts", 24)),
        notify_back_in_stock=_bool(alerts, "notify_back_in_stock", "alerts", True),
    )
    return Settings(
        timezone=timezone,
        http=http_settings,
        sites=tuple(sites),
        alerts=alert_settings,
    )


def load_products(path: Path) -> tuple[ProductConfig, ...]:
    raw = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "products")
    rows = raw.get("products")
    if not isinstance(rows, list):
        raise ConfigError("products.products doit être une liste")
    products: list[ProductConfig] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"products[{index}]")
        name = _str(row, "name", f"products[{index}]")
        try:
            max_price = Decimal(str(row["max_price"]))
        except (KeyError, ArithmeticError) as exc:
            raise ConfigError(f"Prix seuil invalide pour {name}") from exc
        if max_price <= 0:
            raise ConfigError(f"Prix seuil invalide pour {name}")
        products.append(
            ProductConfig(
                name=name,
                max_price=max_price,
                enabled=_bool(row, "enabled", f"products[{index}]", True),
                aliases=tuple(str(item) for item in row.get("aliases", [])),
                required_tokens=tuple(str(item) for item in row.get("required_tokens", [])),
                excluded_tokens=tuple(str(item) for item in row.get("excluded_tokens", [])),
            )
        )
    return tuple(products)
