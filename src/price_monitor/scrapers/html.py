from __future__ import annotations

import json
import logging
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

LOGGER = logging.getLogger(__name__)


def _safe_log(value: object, limit: int = 300) -> str:
    return " ".join(str(value).split())[:limit]


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

    @property
    def name(self) -> str:
        return self.site.name

    async def search(self, product: ProductConfig) -> list[Offer]:
        try:
            response = await self.client.get(
                self.site.build_search_url(), params={self.site.query_param: product.name}
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            url = _safe_log(exc.request.url)
            raise ScraperError(f"{self.site.name}: HTTP {status} url={url}") from exc
        except httpx.RequestError as exc:
            error_type = type(exc).__name__
            url = _safe_log(exc.request.url)
            raise ScraperError(
                f"{self.site.name}: erreur réseau {error_type} url={url}"
            ) from exc

        LOGGER.info(
            "Réponse HTTP site=%s status=%d octets=%d type=%s url=%s",
            self.site.name,
            response.status_code,
            len(response.content),
            _safe_log(response.headers.get("content-type", "inconnu"), 100),
            _safe_log(response.url),
        )
        return self.parse(response.text, product)[: self.max_results]

    def parse(self, html: str, product: ProductConfig) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        cards_detected = len(soup.select(self.site.card_selector))
        card_offers = self._parse_cards(soup, product)
        json_ld_offers = self._parse_json_ld(soup, product)
        unique: dict[str, Offer] = {}
        for offer in (*card_offers, *json_ld_offers):
            current = unique.get(offer.url)
            if current is None or offer.price < current.price:
                unique[offer.url] = offer
        result = sorted(unique.values(), key=lambda offer: (-offer.match_score, offer.price))
        LOGGER.info(
            "Analyse HTML site=%s cartes=%d offres_cartes=%d offres_json_ld=%d "
            "offres_uniques=%d",
            self.site.name,
            cards_detected,
            len(card_offers),
            len(json_ld_offers),
            len(result),
        )
        return result

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
                if not self._is_product(item.get("@type")):
                    continue
                title = str(item.get("name", "")).strip()
                offer_values = item.get("offers", [])
                if isinstance(offer_values, dict):
                    offer_values = [offer_values]
                if not isinstance(offer_values, list):
                    continue
                for offer_data in offer_values:
                    if not isinstance(offer_data, dict):
                        continue
                    price_value = offer_data.get("price", offer_data.get("lowPrice"))
                    url = str(item.get("url") or offer_data.get("url") or "").strip()
                    if not title or not url or price_value is None:
                        continue
                    try:
                        price = parse_price(str(price_value))
                    except ValueError:
                        continue
                    availability = str(offer_data.get("availability", "InStock")).lower()
                    image_url = self._image_url(item.get("image"))
                    offers.append(
                        Offer(
                            query=product.name,
                            title=title,
                            site=self.site.name,
                            price=price,
                            currency=str(offer_data.get("priceCurrency", "MAD")),
                            available=(
                                "outofstock" not in availability
                                and "soldout" not in availability
                            ),
                            url=urljoin(self.site.base_url, url),
                            image_url=image_url,
                            match_score=match_score(product, title),
                        )
                    )
        return offers

    @staticmethod
    def _is_product(value: object) -> bool:
        values = value if isinstance(value, list) else [value]
        return any(str(item).rstrip("/").rsplit("/", 1)[-1] == "Product" for item in values)

    def _image_url(self, value: object) -> str | None:
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("url") or value.get("contentUrl")
        if isinstance(value, str) and value.strip():
            return urljoin(self.site.base_url, value.strip())
        return None

    @classmethod
    def _objects(cls, payload: Any) -> Iterable[dict[str, Any]]:
        if isinstance(payload, dict):
            yield payload
            for value in payload.values():
                yield from cls._objects(value)
        elif isinstance(payload, list):
            for item in payload:
                yield from cls._objects(item)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()
