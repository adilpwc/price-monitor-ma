from __future__ import annotations

import logging
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from ..config import HttpSettings, MatchingSettings, ScraperSettings
from ..matching import is_match
from ..models import Offer, ProductConfig
from .base import BaseScraper, ScraperError

LOG = logging.getLogger(__name__)

# Regex pour extraire les prix (format: 1 234.56 MAD ou 1,234.56 DH)
PRICE_REGEX = re.compile(
    r"(?P<amount>\d{1,3}(?:[\s,.]\d{3})*(?:[,.]\d{2})?|\d+(?:[,.]\d{2})?)\s*(?:dh|dhs|mad|درهم)",
    re.IGNORECASE,
)


class JumiaScraper(BaseScraper):
    name = "Jumia"

    def __init__(self, settings: ScraperSettings, http: HttpSettings,
                 matching: MatchingSettings, client: httpx.Client | None = None) -> None:
        self.settings, self.http, self.matching = settings, http, matching
        timeout = httpx.Timeout(http.timeout_seconds, connect=http.connect_timeout_seconds)
        self.client = client or httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={
                "User-Agent": http.user_agent,
                "Accept-Language": "fr-MA,fr;q=0.9,en;q=0.8"
            },
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
        raise ScraperError(f"Jumia inaccessible après plusieurs tentatives: {last_error}")

    def search(self, product: ProductConfig) -> list[Offer]:
        if not self.settings.enabled:
            return []
        
        # Construire l'URL de recherche Jumia
        url = urljoin(self.settings.base_url + "/", self.settings.search_path.lstrip("/"))
        
        try:
            response = self._get(url, {self.settings.query_parameter: product.name})
        except ScraperError:
            raise
        
        offers = self.parse_html(response.text, product, response.url)
        
        # Dédupliquer par URL
        unique: dict[str, Offer] = {}
        for offer in offers:
            existing = unique.get(offer.url)
            if existing is None or offer.match_score > existing.match_score:
                unique[offer.url] = offer
        
        return sorted(unique.values(), key=lambda x: (x.price, -x.match_score))[:self.settings.max_results]

    def parse_html(self, html: str, product: ProductConfig, page_url: str = "") -> list[Offer]:
        soup = BeautifulSoup(html, "html.parser")
        offers = self._parse_product_cards(soup, product, page_url)
        return offers

    def _parse_product_cards(self, soup: BeautifulSoup, product: ProductConfig, 
                             page_url: str) -> list[Offer]:
        """Parse les cartes produits de Jumia"""
        results: list[Offer] = []
        
        # Sélecteurs CSS pour les produits Jumia
        selectors = "article.prd, article.product-card, div[data-sku], div.product-item"
        
        for card in soup.select(selectors):
            try:
                # Extraire le titre
                title_el = card.select_one(".name, h3, h2, a.product-name")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title:
                    continue
                
                # Vérifier le matching
                matched, score = is_match(product, title, self.matching)
                if not matched:
                    continue
                
                # Extraire l'URL du produit
                link_el = card.select_one("a[href]")
                if not link_el:
                    continue
                href = link_el.get("href")
                if not href:
                    continue
                url = urljoin(self.settings.base_url, href)
                
                # Nettoyer l'URL (supprimer les paramètres de suivi)
                url = url.split("?")[0] if "?" in url else url
                
                # Extraire le prix du texte de la carte
                card_text = card.get_text(" ", strip=True)
                price = self._extract_price(card_text)
                
                if price is None:
                    LOG.debug("Prix Jumia illisible pour %s", title)
                    continue
                
                # Déterminer la disponibilité
                text_lower = card_text.lower()
                unavailable = any(x in text_lower for x in (
                    "rupture", "stock épuisé", "indisponible", "out of stock", 
                    "rupture de stock", "non disponible"
                ))
                
                # Extraire l'image (optionnel)
                image_el = card.select_one("img")
                image_url = None
                if image_el:
                    image_url = image_el.get("data-src") or image_el.get("src")
                    if image_url:
                        image_url = urljoin(self.settings.base_url, str(image_url))
                
                # Créer l'offre
                results.append(Offer(
                    product.name, title, self.name, price, "MAD", not unavailable,
                    url, image_url, score
                ))
                
            except Exception as e:
                LOG.debug("Erreur lors du parsing d'une carte Jumia: %s", e)
                continue
        
        return results

    def _extract_price(self, text: str) -> Decimal | None:
        """Extrait le prix du texte en utilisant regex"""
        matches = list(PRICE_REGEX.finditer(text))
        
        if not matches:
            return None
        
        for match in matches:
            try:
                price_str = match.group("amount")
                # Normaliser le format du prix
                price_str = price_str.replace(" ", "")  # Supprimer les espaces
                
                # Gérer les séparateurs de milliers et décimaux
                if "," in price_str and "." in price_str:
                    # Format comme "1.234,56" ou "1,234.56"
                    if price_str.rfind(",") > price_str.rfind("."):
                        # Format européen "1.234,56"
                        normalized = price_str.replace(".", "").replace(",", ".")
                    else:
                        # Format US "1,234.56"
                        normalized = price_str.replace(",", "")
                elif "," in price_str:
                    # Peut être "1,234" (milliers) ou "1,56" (décimal)
                    parts = price_str.split(",")
                    if len(parts[-1]) == 3:
                        # Séparateur de milliers
                        normalized = price_str.replace(",", "")
                    else:
                        # Séparateur décimal
                        normalized = price_str.replace(",", ".")
                elif "." in price_str:
                    # Peut être "1.234" (milliers) ou "1.56" (décimal)
                    parts = price_str.split(".")
                    if len(parts[-1]) == 3:
                        # Séparateur de milliers
                        normalized = price_str.replace(".", "")
                    else:
                        # Séparateur décimal - pas de changement
                        normalized = price_str
                else:
                    # Pas de séparateur
                    normalized = price_str
                
                price = Decimal(normalized).quantize(Decimal("0.01"))
                
                if price > 0:
                    return price
            except (ValueError, InvalidOperation):
                continue
        
        return None
