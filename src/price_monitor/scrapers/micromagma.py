from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

import httpx

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
        
        # Construire l'URL de l'API
        api_url = urljoin(self.settings.base_url + "/", "api/products/criteria")
        
        # Paramètres de la requête
        params = {
            self.settings.query_parameter: product.name,
            "page": "0",
            "size": str(self.settings.max_results),
        }
        
        try:
            response = self._get(api_url, params)
        except ScraperError:
            raise
        
        try:
            data = response.json()
        except ValueError as exc:
            raise ScraperError(f"Réponse JSON invalide de MicroMagma: {exc}") from exc
        
        offers = self.parse_json(data, product)
        
        # Dédupliquer par URL
        unique: dict[str, Offer] = {}
        for offer in offers:
            existing = unique.get(offer.url)
            if existing is None or offer.match_score > existing.match_score:
                unique[offer.url] = offer
        
        return sorted(unique.values(), key=lambda x: (x.price, -x.match_score))[:self.settings.max_results]

    def parse_json(self, data: dict, product: ProductConfig) -> list[Offer]:
        """Parse la réponse JSON de l'API MicroMagma"""
        results: list[Offer] = []
        
        # Accéder à la liste des produits (dans 'content')
        products = data.get("content", [])
        if not isinstance(products, list):
            LOG.warning("Structure JSON inattendue de MicroMagma: pas de champ 'content'")
            return results
        
        for item in products:
            if not isinstance(item, dict):
                continue
            
            # Extraire le titre
            title = str(item.get("name", "")).strip()
            if not title:
                continue
            
            # Vérifier le matching
            matched, score = is_match(product, title, self.matching)
            if not matched:
                continue
            
            # Extraire le prix (utiliser 'price' si disponible, sinon 'minPrice')
            price_data = item.get("price")
            if price_data is None:
                price_data = item.get("minPrice")
            if price_data is None:
                continue
            
            try:
                price = parse_price(str(price_data))
            except ValueError:
                LOG.debug("Prix MicroMagma illisible pour %s: %s", title, price_data)
                continue
            
            # Construire l'URL du produit
            product_id = item.get("id")
            alias = item.get("alias", "")
            if product_id and alias:
                url = f"{self.settings.base_url}/{item.get('familyAlias', 'item')}/item/{product_id}-{alias}"
            else:
                url = f"{self.settings.base_url}/product/{product_id}" if product_id else None
            
            if not url:
                continue
            
            # Extraire l'image
            image_url = item.get("imageUrl")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.settings.base_url, image_url)
            
            # Disponibilité (par défaut disponible)
            available = True
            
            # Créer l'offre
            results.append(Offer(
                product.name, title, self.name, price, "MAD", available,
                url, image_url, score
            ))
        
        return results
