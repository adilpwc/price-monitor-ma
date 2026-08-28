from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from price_monitor.config import Settings, load_settings
from price_monitor.models import ProductConfig
from price_monitor.scrapers.html import HtmlScraper


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings(Path("config/settings.yml"))


@pytest.mark.parametrize(
    ("site_name", "card_class", "title_class", "price_class", "link_class"),
    [
        ("jumia", "prd", "name", "prc", "core"),
        ("electroplanet", "product-item", "product-item-name", "price", "product-item-link"),
        ("ultrapc", "product-miniature", "product-title", "price", "thumbnail"),
        ("micromagma", "product-miniature", "product-title", "price", "product-link"),
        ("marjanemall", "product-card", "product-title", "current-price", "product-link"),
        ("cosmos", "product-item", "product-item-name", "price", "product-item-link"),
    ],
)
def test_each_site_fixture(
    settings: Settings,
    site_name: str,
    card_class: str,
    title_class: str,
    price_class: str,
    link_class: str,
) -> None:
    site = next(item for item in settings.sites if item.name == site_name)
    html = f"""
      <article class="{card_class}">
        <a class="{link_class}" href="/p/macbook-air-m2">
          <img data-src="/images/macbook.jpg" />
          <h3 class="{title_class}">Apple MacBook Air 13 M2 8 Go 256 Go</h3>
        </a>
        <div class="{price_class}">9 499,00 MAD</div>
        <span>En stock</span>
      </article>
    """
    scraper = HtmlScraper(site, settings.http)
    offers = scraper.parse(
        html,
        ProductConfig(
            name="MacBook Air M2",
            max_price=Decimal("10000"),
            required_tokens=("macbook", "air", "m2"),
        ),
    )
    assert len(offers) == 1
    assert offers[0].site == site_name
    assert offers[0].price == Decimal("9499.00")
    assert offers[0].available is True
    assert offers[0].url.startswith(site.base_url)
    assert offers[0].match_score >= 72
    asyncio.run(scraper.aclose())
