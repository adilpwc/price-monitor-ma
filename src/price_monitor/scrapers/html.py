from __future__ import annotations

import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from price_monitor.config import HttpSettings, SiteSettings
from price_monitor.matching import match_score
from price_monitor.models import Offer, ProductConfig
from price_monitor.parsing import parse_price

from .base import BaseScraper, ScraperError


class HtmlScraper(BaseScraper):
    def __init__(
        self,
        site: SiteSettings,
        http: HttpSettings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.site = site
        self.max_results = http.max_results_per_site
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=http.timeout_seconds,
            headers={"User-Agent": http.user_agent, "Accept-Language": "fr-MA,fr;q=0.9"},
            follow_redirects=True,
        )

    async def search(self, product: ProductConfig) -> list[Offer]:
        try:
            response = await self.client.get(
                self.site.build_search_url(), params={self.site.query_param: product.name}
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"{self.site.name}: échec HTTP") from exc
        return self.parse(response.text, product)[: self.max_results]

    def parse(self, html: str, product: ProductConfig) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = self._parse_cards(soup, product)
        if not offers:
            offers = self._parse_json_ld(soup, product)
        unique: dict[str, Offer] = {}
        for offer in offers:
            current = unique.get(offer.url)
            if current is None or offer.price < current.price:
                unique[offer.url] = offer
        return sorted(unique.values(), key=lambda offer: (-offer.match_score, offer.price))

    def _parse_cards(self, soup: BeautifulSoup, product: ProductConfig) -> list[Offer]:
        offers: list[Offer] = []
        for card in soup.select(self.site.card_selector):
            title_node = card.select_one(self.site.title_selector)
            price_node = card.select_one(self.site.price_selector)
            link_node = card.select_one(self.site.link_selector)
            if not title_node or not price_node or not isinstance(link_node, Tag):
                continue
            href = link_node.get("href")
            if not isinstance(href, str) or not href:
                continue
            title = title_node.get_text(" ", strip=True)
            try:
                price = self._price_from_node(price_node)
            except ValueError:
                continue
            image_url = None
            if self.site.image_selector:
                image_node = card.select_one(self.site.image_selector)
                if isinstance(image_node, Tag):
                    src = image_node.get("src") or image_node.get("data-src")
                    if isinstance(src, str):
                        image_url = urljoin(self.site.base_url, src)
            content = card.get_text(" ", strip=True).lower()
            if self.site.availability_selector:
                availability = card.select_one(self.site.availability_selector)
                content = availability.get_text(" ", strip=True).lower() if availability else ""
            available = not any(token in content for token in self.site.unavailable_text)
            offers.append(
                Offer(
                    query=product.name,
                    title=title,
                    site=self.site.name,
                    price=price,
                    currency="MAD",
                    available=available,
                    url=urljoin(self.site.base_url, href),
                    image_url=image_url,
                    match_score=match_score(product, title),
                )
            )
        return offers

    @staticmethod
    def _price_from_node(node: Tag) -> Decimal:
        content = node.get("content")
        return parse_price(content if isinstance(content, str) else node.get_text(" ", strip=True))

    def _parse_json_ld(self, soup: BeautifulSoup, product: ProductConfig) -> list[Offer]:
        offers: list[Offer] = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                payload = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for item in self._objects(payload):
                if item.get("@type") != "Product":
                    continue
                offer_data = item.get("offers", {})
                if isinstance(offer_data, list):
                    offer_data = offer_data[0] if offer_data else {}
                if not isinstance(offer_data, dict):
                    continue
                title = str(item.get("name", "")).strip()
                url = str(item.get("url") or offer_data.get("url") or "").strip()
                try:
                    price = parse_price(str(offer_data["price"]))
                except (KeyError, ValueError):
                    continue
                availability = str(offer_data.get("availability", "InStock"))
                offers.append(
                    Offer(
                        query=product.name,
                        title=title,
                        site=self.site.name,
                        price=price,
                        currency=str(offer_data.get("priceCurrency", "MAD")),
                        available="OutOfStock" not in availability,
                        url=urljoin(self.site.base_url, url),
                        match_score=match_score(product, title),
                    )
                )
        return offers

    @classmethod
    def _objects(cls, payload: Any) -> Iterable[dict[str, Any]]:
        if isinstance(payload, dict):
            yield payload
            graph = payload.get("@graph", [])
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict):
                        yield item
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()
