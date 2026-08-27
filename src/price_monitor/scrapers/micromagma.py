from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import HttpSettings, MatchingSettings, ScraperSettings
from ..matching import is_match
from ..models import Offer, ProductConfig
from ..parsing import parse_price
from .base import BaseScraper, ScraperError

LOG = logging.getLogger(__name__)


class MicroMagmaScraper(BaseScraper):
    name = "MicroMagma"

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

    def _get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.http.retries + 1):
            try:
                response = self.client.get(url, params=params or {})
                response.raise_for_status()
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.http.retries:
                    time.sleep(self.http.retry_backoff_seconds * (2 ** attempt))
        raise ScraperError(f"MicroMagma inaccessible après plusieurs tentatives: {last_error}")

    def search(self, product: ProductConfig) -> list[Offer]:
        if not self.settings.enabled:
            return []
        
        # Construire l'URL de la catégorie laptops
        url = urljoin(self.settings.base_url + "/", self.settings.search_path.lstrip("/"))
        
        # Optionnel : ajouter le paramètre de recherche s'il existe
        params = {}
        if self.settings.query_parameter:
            params = {self.settings.query_parameter: product.name}
        
        try:
            response = self._get(url, params if params else None)
        except ScraperError:
            raise
        
        offers = self.parse_html(response.text, product)
        
        # Dédupliquer par URL
        unique: dict[str, Offer] = {}
        for offer in offers:
            existing = unique.get(offer.url)
            if existing is None or offer.match_score > existing.match_score:
                unique[offer.url] = offer
        
        return sorted(unique.values(), key=lambda x: (x.price, -x.match_score))[:self.settings.max_results]

    def parse_html(self, html: str, product: ProductConfig) -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = self._parse_product_cards(soup, product)
        return offers

    def _parse_product_cards(self, soup: BeautifulSoup, product: ProductConfig) -> list[Offer]:
        """Parse les cartes produits de MicroMagma"""
        results: list[Offer] = []
        
        # Sélecteurs pour les produits MicroMagma
        # À adapter selon le HTML réel du site
        selectors = "div.product-item, div.product-card, li.product, article.product, div[class*='product']"
        
        for card in soup.select(selectors):
            # Récupérer le titre
            title_el = card.select_one("h2, h3, .product-name, .product-title, a.product-link")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            
            # Récupérer le prix
            price_el = card.select_one(".price, .product-price, [data-price], .prix, span[class*='price']")
            if not price_el:
                continue
            
            price_text = price_el.get("data-price") or price_el.get_text(strip=True)
            try:
                price = parse_price(price_text)
            except ValueError:
                LOG.debug("Prix MicroMagma illisible pour %s: %s", title, price_text)
                continue
            
            # Vérifier le matching
            matched, score = is_match(product, title, self.matching)
            if not matched:
                continue
            
            # Récupérer l'URL du produit
            link_el = card.select_one("a[href]")
            if not link_el:
                continue
            href = link_el.get("href")
            if not href:
                continue
            
            # Déterminer la disponibilité
            text = card.get_text(" ", strip=True).lower()
            unavailable = any(x in text for x in ("rupture", "stock épuisé", "indisponible", "out of stock", "rupture de stock"))
            
            # Récupérer l'image (optionnel)
            image_el = card.select_one("img")
            image_url = None
            if image_el:
                image_url = image_el.get("data-src") or image_el.get("src")
                if image_url:
                    image_url = urljoin(self.settings.base_url, str(image_url))
            
            # Créer l'offre
            results.append(Offer(
                product.name, title, self.name, price, "MAD", not unavailable,
                urljoin(self.settings.base_url, str(href)), image_url, score
            ))
        
        return results
