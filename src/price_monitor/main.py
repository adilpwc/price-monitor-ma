from __future__ import annotations

import argparse
import logging
import time

from .config import ConfigError, load_products, load_settings
from .notifications.telegram import TelegramNotifier
from .scrapers.base import ScraperError
from .scrapers.ultrapc import UltraPCScraper
from .scrapers.micromagma import MicroMagmaScraper
from .storage import PriceRepository

LOG = logging.getLogger("price_monitor")


def run(settings_path: str, products_path: str, dry_run: bool = False) -> int:
    settings = load_settings(settings_path)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    products = load_products(products_path)
    repository = PriceRepository(settings.database_path)
    repository.initialize()
    
    # Créer les scrapers
    scrapers = [
        UltraPCScraper(settings.ultrapc, settings.http, settings.matching),
        MicroMagmaScraper(settings.micromagma, settings.http, settings.matching),
    ]
    
    notifier = TelegramNotifier()
    errors = 0
    try:
        for product in products:
            product_id = repository.upsert_product(product)
            for scraper in scrapers:
                if not scraper.settings.enabled:
                    continue
                LOG.info("Recherche de %s sur %s", product.name, scraper.name)
                try:
                    offers = scraper.search(product)
                except ScraperError:
                    LOG.exception("Échec du scraper %s pour %s", scraper.name, product.name)
                    errors += 1
                    continue
                if not offers:
                    LOG.info("Aucune offre pertinente trouvée pour %s sur %s", product.name, scraper.name)
                    continue
                for offer in offers:
                    repository.add_offer(product_id, offer)
                    stats = repository.stats(product_id, offer.site, offer.url)
                    decision = repository.alert_decision(
                        product_id, product, offer,
                        settings.alerts.significant_change_percent,
                        settings.alerts.significant_change_mad,
                    )
                    LOG.info("%s: %s MAD, disponible=%s, score=%.1f, alerte=%s, URL: %s",
                             offer.title, offer.price, offer.available, offer.match_score, decision.reason, offer.url)
                    if settings.alerts.enabled and decision.should_notify:
                        message = notifier.build_message(product, offer, stats)
                        if dry_run:
                            LOG.info("Mode dry-run, notification non envoyée:\n%s", message)
                        elif notifier.configured:
                            try:
                                notifier.send(message)
                                repository.mark_alerted(product_id, offer)
                            except Exception:
                                LOG.exception("Échec de notification Telegram")
                                errors += 1
                        else:
                            LOG.warning("Telegram non configuré; alerte non envoyée")
                # Délai entre les requêtes
                time.sleep(settings.http.delay_between_requests_seconds)
        return 1 if errors else 0
    finally:
        for scraper in scrapers:
            scraper.close()
        notifier.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Surveille les prix marocains")
    parser.add_argument("--settings", default="config/settings.yml")
    parser.add_argument("--products", default="config/products.yml")
    parser.add_argument("--dry-run", action="store_true", help="N'envoie aucune notification")
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.settings, args.products, args.dry_run))
    except ConfigError as exc:
        LOG.error("Configuration invalide: %s", exc)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    cli()
