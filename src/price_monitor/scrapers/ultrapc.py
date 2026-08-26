from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import HttpSettings, MatchingSettings, ScraperSettings
from ..matching import is_match
from ..models import Offer, ProductConfig
from ..parsing import parse_price
from .base import BaseScraper, ScraperError

LOG = logging.getLogger(__name__)


class UltraPCScraper(BaseScraper):
    name = "UltraPC"

    def __init__(self, settings: ScraperSettings, http: HttpSettings,
                 matching: MatchingSettings, client: httpx.Client | None = None) -> None:
        self.settings, self.http, self.matching = settings, http, matching
        timeout = httpx.Timeout(http.timeout_seconds, connect=http.connect_timeout_seconds)
        self.client = client or httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": http.user_agent, "Accept-Language": "fr-FR,fr;q=0.9"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _get(self, url: str, params: dict[str, str]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.http.retries + 1):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.http.retries:
                    time.sleep(self.http.retry_backoff_seconds * (2 ** attempt))
        raise ScraperError(f"UltraPC inaccessible après plusieurs tentatives: {last_error}")

    def search(self, product: ProductConfig) -> list[Offer]:
        if not self.settings.enabled:
            return []
        url = urljoin(self.settings.base_url + "/", self.settings.search_path.lstrip("/"))
        response = self._get(url, {self.settings.query_parameter: product.name})
        offers = self.parse_html(response.text, product)
        unique: dict[str, Offer] = {}
        for offer in offers:
            existing = unique.get(offer.url)
            if existing is None or offer.match_score > existing.match_score:
                unique[offer.url] = offer
        return sorted(unique.values(), key=lambda x: (x.price, -x.match_score))[:self.settings.max_results]

    def parse_html(self, html: str, product: ProductConfig) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = self._parse_cards(soup, product)
        if not offers:
            offers = self._parse_json_ld(soup, product)
        return offers

    def _parse_cards(self, soup: BeautifulSoup, product: ProductConfig) -> list[Offer]:
        selectors = "article.product-miniature, article.product_item, .product-miniature, .ajax_block_product"
        results: list[Offer] = []
        for card in soup.select(selectors):
            title_el = card.select_one(".product-title a, h2 a, h3 a, a.product-name")
            price_el = card.select_one(".product-price-and-shipping .price, .price, [itemprop='price']")
            if not title_el or not price_el:
                continue
            title = title_el.get_text(" ", strip=True)
            matched, score = is_match(product, title, self.matching)
            if not matched:
                continue
            try:
                price = parse_price(price_el.get("content") or price_el.get_text(" ", strip=True))
            except ValueError:
                LOG.warning("Prix UltraPC illisible pour %s", title)
                continue
            href = title_el.get("href")
            if not href:
                continue
            text = card.get_text(" ", strip=True).lower()
            unavailable = any(x in text for x in ("rupture de stock", "stock épuisé", "indisponible"))
            image = card.select_one("img")
            image_url = None
            if image:
                image_url = image.get("data-src") or image.get("src")
                if image_url:
                    image_url = urljoin(self.settings.base_url, str(image_url))
            results.append(Offer(product.name, title, self.name, price, "MAD", not unavailable,
                                 urljoin(self.settings.base_url, str(href)), image_url, score))
        return results

    def _parse_json_ld(self, soup: BeautifulSoup, product: ProductConfig) -> list[Offer]:
        found: list[Offer] = []
        nodes: list[Any] = []
        for script in soup.select("script[type='application/ld+json']"):
            try:
                value = json.loads(script.string or "")
                nodes.extend(value if isinstance(value, list) else [value])
            except json.JSONDecodeError:
                continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            candidates = node.get("itemListElement", [node])
            if not isinstance(candidates, list):
                candidates = [node]
            for item in candidates:
                if isinstance(item, dict) and isinstance(item.get("item"), dict):
                    item = item["item"]
                if not isinstance(item, dict):
                    continue
                title = str(item.get("name", ""))
                matched, score = is_match(product, title, self.matching)
                offer_data = item.get("offers", {})
                if isinstance(offer_data, list):
                    offer_data = offer_data[0] if offer_data else {}
                if not matched or not isinstance(offer_data, dict) or "price" not in offer_data:
                    continue
                try:
                    price = parse_price(str(offer_data["price"]))
                except ValueError:
                    continue
                availability = str(offer_data.get("availability", "")).lower()
                available = "outofstock" not in availability
                product_url = str(item.get("url") or offer_data.get("url") or "")
                if product_url:
                    found.append(Offer(product.name, title, self.name, price,
                                       str(offer_data.get("priceCurrency", "MAD")).upper(), available,
                                       urljoin(self.settings.base_url, product_url),
                                       str(item.get("image")) if item.get("image") else None, score))
        return found
