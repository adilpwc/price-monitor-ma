from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .models import ProductConfig


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HttpSettings:
    timeout_seconds: float
    connect_timeout_seconds: float
    retries: int
    retry_backoff_seconds: float
    delay_between_requests_seconds: float
    user_agent: str


@dataclass(frozen=True, slots=True)
class MatchingSettings:
    minimum_score: float
    token_score_weight: float
    ratio_score_weight: float


@dataclass(frozen=True, slots=True)
class AlertSettings:
    enabled: bool
    significant_change_percent: Decimal
    significant_change_mad: Decimal
    notify_back_in_stock: bool


@dataclass(frozen=True, slots=True)
class ScraperSettings:
    enabled: bool
    base_url: str
    search_path: str
    query_parameter: str
    max_results: int


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    currency: str
    timezone: str
    log_level: str
    http: HttpSettings
    matching: MatchingSettings
    alerts: AlertSettings
    ultrapc: ScraperSettings


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Fichier de configuration introuvable: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"La racine YAML doit être un objet: {path}")
    return raw


def load_settings(path: str | Path | None = None) -> Settings:
    file_path = Path(path or os.getenv("PRICE_MONITOR_CONFIG", "config/settings.yml"))
    raw = _read_yaml(file_path)
    try:
        app, http, matching = raw["app"], raw["http"], raw["matching"]
        alerts, ultra = raw["alerts"], raw["scrapers"]["ultrapc"]
        token_weight = float(matching["token_score_weight"])
        ratio_weight = float(matching["ratio_score_weight"])
        if abs(token_weight + ratio_weight - 1.0) > 0.001:
            raise ConfigError("La somme des poids de matching doit être égale à 1")
        return Settings(
            database_path=Path(app["database_path"]),
            currency=str(app.get("currency", "MAD")).upper(),
            timezone=str(app.get("timezone", "Africa/Casablanca")),
            log_level=os.getenv("LOG_LEVEL", str(app.get("log_level", "INFO"))).upper(),
            http=HttpSettings(
                timeout_seconds=float(http["timeout_seconds"]),
                connect_timeout_seconds=float(http["connect_timeout_seconds"]),
                retries=int(http["retries"]),
                retry_backoff_seconds=float(http["retry_backoff_seconds"]),
                delay_between_requests_seconds=float(http["delay_between_requests_seconds"]),
                user_agent=str(http["user_agent"]),
            ),
            matching=MatchingSettings(float(matching["minimum_score"]), token_weight, ratio_weight),
            alerts=AlertSettings(
                bool(alerts["enabled"]), Decimal(str(alerts["significant_change_percent"])),
                Decimal(str(alerts["significant_change_mad"])), bool(alerts["notify_back_in_stock"]),
            ),
            ultrapc=ScraperSettings(
                bool(ultra["enabled"]), str(ultra["base_url"]).rstrip("/"),
                str(ultra["search_path"]), str(ultra["query_parameter"]), int(ultra["max_results"]),
            ),
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ConfigError(f"Configuration invalide dans {file_path}: {exc}") from exc


def load_products(path: str | Path = "config/products.yml") -> list[ProductConfig]:
    raw = _read_yaml(Path(path))
    rows = raw.get("products", [])
    if not isinstance(rows, list):
        raise ConfigError("products doit être une liste")
    products: list[ProductConfig] = []
    for index, row in enumerate(rows):
        try:
            price = Decimal(str(row["max_price"]))
            if price <= 0:
                raise ConfigError("max_price doit être positif")
            products.append(ProductConfig(
                name=str(row["name"]).strip(), max_price=price,
                enabled=bool(row.get("enabled", True)),
                aliases=tuple(map(str, row.get("aliases", []))),
                required_tokens=tuple(str(x).lower() for x in row.get("required_tokens", [])),
                excluded_tokens=tuple(str(x).lower() for x in row.get("excluded_tokens", [])),
            ))
        except (KeyError, TypeError, InvalidOperation) as exc:
            raise ConfigError(f"Produit #{index + 1} invalide: {exc}") from exc
    return [p for p in products if p.enabled]
