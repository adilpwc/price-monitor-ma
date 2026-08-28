from __future__ import annotations

import asyncio
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from price_monitor.config import Settings, load_settings
from price_monitor.models import ProductConfig
from price_monitor.scrapers.base import ScraperError
from price_monitor.scrapers.html import HtmlScraper


@pytest.fixture(scope="module")
def settings() -> Settings:
    return load_settings(Path("config/settings.yml"))


def test_http_403_is_not_retried_and_is_explicit(settings: Settings) -> None:
    site = settings.sites[0]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(403, request=request, text="Forbidden")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = HtmlScraper(site, settings.http, client)
    with pytest.raises(ScraperError, match="HTTP 403 accès automatisé refusé"):
        asyncio.run(scraper.search(ProductConfig("MacBook Air M2", Decimal("10000"))))
    assert calls == 1
    asyncio.run(client.aclose())


def test_product_urls_are_canonicalized_and_external_domains_rejected(
    settings: Settings,
) -> None:
    site = replace(settings.sites[0], product_url_include=("/p/",))
    scraper = HtmlScraper(site, settings.http)
    html = """
    <article class="prd">
      <a class="core" href="/p/macbook?utm_source=test&variant=256#details">
        <h3 class="name">MacBook Air M2</h3>
      </a>
      <div class="prc">9 499 MAD</div>
    </article>
    <article class="prd">
      <a class="core" href="https://evil.example/p/macbook">
        <h3 class="name">MacBook Air M2</h3>
      </a>
      <div class="prc">1 MAD</div>
    </article>
    """
    offers = scraper.parse(html, ProductConfig("MacBook Air M2", Decimal("10000")))
    assert len(offers) == 1
    assert offers[0].url == f"{site.base_url}/p/macbook?variant=256"
    asyncio.run(scraper.aclose())


@pytest.mark.parametrize(
    ("site_name", "card_class", "title_class", "product_path"),
    [
        ("biougnach", "product-miniature", "product-title", "/p/macbook-air-m2"),
        ("electrosalam", "card-wrapper", "card__heading", "/products/macbook-air-m2"),
        ("mymarket", "product-card", "product-title", "/p/macbook-air-m2"),
    ],
)
def test_new_active_provider_fixtures(
    settings: Settings,
    site_name: str,
    card_class: str,
    title_class: str,
    product_path: str,
) -> None:
    site = next(item for item in settings.sites if item.name == site_name)
    html = f"""
      <article class="{card_class}">
        <a class="product-title" href="{product_path}">
          <h3 class="{title_class}">Apple MacBook Air 13 M2 8 Go 256 Go</h3>
        </a>
        <div class="price">9 499,00 MAD</div>
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
    assert offers[0].url.startswith(site.base_url)
    asyncio.run(scraper.aclose())


def test_provider_activation_policy(settings: Settings) -> None:
    active = {site.name for site in settings.sites if site.enabled}
    assert {"biougnach", "electrosalam", "mymarket"} <= active
    assert {
        "avito",
        "bringo",
        "decathlon",
        "defacto",
        "ikea",
        "mafiawaystore",
        "palmarosa",
        "planetsport",
    }.isdisjoint(active)
