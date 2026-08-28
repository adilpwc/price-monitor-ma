from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx

from price_monitor.config import load_settings
from price_monitor.models import Offer, ProductConfig
from price_monitor.notifications.telegram import TelegramNotifier
from price_monitor.scrapers.base import BaseScraper
from price_monitor.scrapers.html import HtmlScraper
from price_monitor.storage import PriceStore


class FakeScraper(BaseScraper):
    def __init__(self, offers: list[Offer]) -> None:
        self.offers = offers
        self.closed = False

    async def search(self, product: ProductConfig) -> list[Offer]:
        return self.offers

    async def aclose(self) -> None:
        self.closed = True


def test_json_ld_fallback() -> None:
    settings = load_settings(Path("config/settings.yml"))
    site = settings.sites[0]
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Product","name":"MacBook Air M2",
     "url":"/m2","offers":{"@type":"Offer","price":"9999","priceCurrency":"MAD",
     "availability":"https://schema.org/InStock"}}
    </script>
    """
    scraper = HtmlScraper(site, settings.http)
    offers = scraper.parse(html, ProductConfig("MacBook Air M2", Decimal("10000")))
    assert offers[0].price == Decimal("9999.00")
    assert offers[0].available
    asyncio.run(scraper.aclose())


def test_search_uses_configured_query() -> None:
    settings = load_settings(Path("config/settings.yml"))
    site = settings.sites[0]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params[site.query_param] == "MacBook Air M2"
        return httpx.Response(200, text="<html></html>")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = HtmlScraper(site, settings.http, client)
    result = asyncio.run(scraper.search(ProductConfig("MacBook Air M2", Decimal("10000"))))
    assert result == []
    asyncio.run(client.aclose())


def test_telegram_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier("dummy-token", "123")
    asyncio.run(notifier.client.aclose())
    notifier.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    offer = Offer(
        query="MacBook",
        title="MacBook <Air>",
        site="shop",
        price=Decimal("9000"),
        currency="MAD",
        available=True,
        url="https://shop.ma/p/1?a=1&b=2",
    )
    asyncio.run(notifier.send(ProductConfig("MacBook Air", Decimal("10000")), offer, "first"))
    assert "dummy-token" not in str(captured["body"])
    assert "MacBook" in str(captured["body"])
    asyncio.run(notifier.aclose())


def test_fake_scraper_and_store(tmp_path: Path) -> None:
    scraper = FakeScraper([])
    product = ProductConfig("MacBook Air M2", Decimal("10000"))
    assert asyncio.run(scraper.search(product)) == []
    asyncio.run(scraper.aclose())
    assert scraper.closed
    store = PriceStore(tmp_path / "db.sqlite")
    store.sync_products((product,))
    assert store.product_id(product.name) > 0
    store.close()
