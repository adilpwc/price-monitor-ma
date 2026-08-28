from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from price_monitor.config import ConfigError, load_products, load_settings
from price_monitor.matching import match_score
from price_monitor.models import ProductConfig
from price_monitor.parsing import normalize_text, parse_price


def test_real_configuration_has_six_sites() -> None:
    settings = load_settings(Path("config/settings.yml"))
    products = load_products(Path("config/products.yml"))
    assert len(settings.sites) == 6
    assert str(settings.timezone) == "Africa/Casablanca"
    assert products[0].max_price == Decimal("10000")


def test_string_false_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.yml"
    path.write_text(
        """timezone: Africa/Casablanca
http: {}
alerts: {}
sites:
  shop:
    enabled: "false"
    base_url: https://shop.ma
    search_path: /search
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="booléen"):
        load_settings(path)


def test_price_and_normalization() -> None:
    assert parse_price("9 499,00 MAD") == Decimal("9499.00")
    assert parse_price("14.990 DH") == Decimal("14990.00")
    assert normalize_text("MacBook-Air M²") == "macbook air m2"
    with pytest.raises(ValueError):
        parse_price("gratuit")


def test_matching_uses_token_boundaries() -> None:
    product = ProductConfig(
        "MacBook Air M2",
        Decimal("10000"),
        required_tokens=("m2",),
        excluded_tokens=("pro",),
    )
    assert match_score(product, "Apple MacBook Air M2") > 72
    assert match_score(product, "Apple MacBook Air M20") == 0
    assert match_score(product, "Apple MacBook Pro Air M2") == 0
