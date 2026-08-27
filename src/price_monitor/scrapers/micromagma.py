from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx

from ..config import HttpSettings, MatchingSettings, ScraperSettings
from ..matching import is_match
from ..models import Offer, ProductConfig
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
            
            # Construire l'URL AVANT de traiter le prix (pour les logs)
            product_id = item.get("id")
            alias = item.get("alias", "")
            family_alias = item.get("familyAlias", "laptops")
            
            if product_id and alias:
                url = f"{self.settings.base_url}/{family_alias}/item/{product_id}-{alias}"
            elif product_id:
                url = f"{self.settings.base_url}/product/{product_id}"
            else:
                continue
            
            # Extraire le prix - UTILISER LE PRIX LE PLUS BAS
            # Préférer minPrice (prix en promotion) s'il existe et est plus bas
            price_promo = item.get("minPrice")
            price_normal = item.get("price")
            
            # Sélectionner le prix à utiliser
            if price_promo is not None and price_promo > 0:
                price_to_use = price_promo  # Utiliser le prix promo s'il existe
            elif price_normal is not None and price_normal > 0:
                price_to_use = price_normal
            else:
                LOG.debug("Aucun prix valide pour %s", title)
                continue
            
            try:
                # Convertir directement en Decimal sans passer par parse_price
                # car le prix est déjà un nombre (int/float) du JSON
                if isinstance(price_to_use, (int, float)):
                    price = Decimal(str(price_to_use)).quantize(Decimal("0.01"))
                else:
                    # Si c'est une string, essayer de la parser
                    price = Decimal(str(price_to_use)).quantize(Decimal("0.01"))
            except (ValueError, InvalidOperation) as e:
                LOG.debug("Prix MicroMagma illisible pour %s: %s - %s", title, price_to_use, e)
                continue
            
            # Extraire l'image
            image_url = item.get("imageUrl")
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.settings.base_url, image_url)
            
            # Disponibilité (par défaut disponible)
            available = True
            
            # Créer l'offre
            offer = Offer(
                product.name, title, self.name, price, "MAD", available,
                url, image_url, score
            )
            results.append(offer)
            
            LOG.debug("MicroMagma trouvé: %s - Prix: %s MAD (Promo: %s MAD) - URL: %s", 
                      title, price_normal, price_promo, url)
        
        return results
