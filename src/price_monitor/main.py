from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .config import Settings, load_products, load_settings
from .models import ProductConfig
from .notifications.telegram import TelegramNotifier, format_alert_message
from .scrapers.base import BaseScraper, ScraperError
from .scrapers.html import HtmlScraper
from .storage import PriceStore

LOGGER = logging.getLogger(__name__)
MATCH_THRESHOLD = 72.0


def _safe_log(value: object, limit: int = 300) -> str:
    return " ".join(str(value).split())[:limit]


def build_scrapers(settings: Settings) -> list[BaseScraper]:
    scrapers: list[BaseScraper] = []
    for site in settings.sites:
        if not site.enabled:
            continue
        if site.kind != "html":
            raise ValueError(f"Type de scraper non pris en charge: {site.kind}")
        scrapers.append(HtmlScraper(site, settings.http))
    return scrapers


async def monitor(
    settings_path: Path,
    products_path: Path,
    database_path: Path,
    dry_run: bool,
) -> int:
    settings = load_settings(settings_path)
    products = load_products(products_path)
    enabled_products = tuple(product for product in products if product.enabled)
    store = PriceStore(database_path)
    scrapers = build_scrapers(settings)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    notifier = (
        TelegramNotifier(token, chat_id, settings.http.timeout_seconds)
        if token and chat_id
        else None
    )
    attempts = len(scrapers) * len(enabled_products)
    LOGGER.info(
        "Démarrage mode=%s produits=%d sites=%d tentatives=%d base=%s",
        "dry-run" if dry_run else "réel",
        len(enabled_products),
        len(scrapers),
        attempts,
        _safe_log(database_path),
    )

    failures = 0
    try:
        store.sync_products(products)
        if not enabled_products:
            LOGGER.error("Aucun produit actif dans la configuration")
            return 1
        if not dry_run and notifier is None:
            raise RuntimeError(
                "Secrets Telegram absents; utilisez --dry-run pour tester sans notification"
            )
        for product in enabled_products:
            failures += await _monitor_product(
                product, settings, scrapers, store, notifier, dry_run
            )
    finally:
        await asyncio.gather(*(scraper.aclose() for scraper in scrapers))
        if notifier:
            await notifier.aclose()
        store.close()

    exit_code = 1 if attempts > 0 and failures == attempts else 0
    LOGGER.info(
        "Fin surveillance tentatives=%d réussies=%d échecs=%d code_sortie=%d",
        attempts,
        attempts - failures,
        failures,
        exit_code,
    )
    return exit_code


async def _monitor_product(
    product: ProductConfig,
    settings: Settings,
    scrapers: list[BaseScraper],
    store: PriceStore,
    notifier: TelegramNotifier | None,
    dry_run: bool,
) -> int:
    failures = 0
    product_id = store.product_id(product.name)
    LOGGER.info(
        "Produit début nom=%s seuil=%s MAD sites=%d",
        _safe_log(product.name, 160),
        product.max_price,
        len(scrapers),
    )
    for scraper in scrapers:
        LOGGER.info(
            "Recherche début produit=%s site=%s",
            _safe_log(product.name, 160),
            scraper.name,
        )
        try:
            offers = await scraper.search(product)
        except ScraperError as exc:
            failures += 1
            LOGGER.error(
                "Recherche échouée produit=%s site=%s erreur=%s",
                _safe_log(product.name, 160),
                scraper.name,
                _safe_log(exc),
            )
            continue

        matched = 0
        under_threshold = 0
        alerts = 0
        if not offers:
            LOGGER.warning(
                "Aucune offre extraite produit=%s site=%s; vérifier sélecteurs, JSON-LD "
                "ou rendu JavaScript",
                _safe_log(product.name, 160),
                scraper.name,
            )
        for offer in offers:
            store.record(product_id, offer)
            selected = offer.match_score >= MATCH_THRESHOLD
            affordable = selected and offer.available and offer.price <= product.max_price
            matched += int(selected)
            under_threshold += int(affordable)
            if not affordable:
                LOGGER.debug(
                    "Offre ignorée site=%s prix=%s %s score=%.1f disponible=%s "
                    "seuil=%s titre=%s",
                    scraper.name,
                    offer.price,
                    _safe_log(offer.currency, 12),
                    offer.match_score,
                    offer.available,
                    product.max_price,
                    _safe_log(offer.title, 180),
                )
                continue

            LOGGER.info(
                "Offre sous seuil site=%s prix=%s %s seuil=%s score=%.1f "
                "titre=%s url=%s",
                scraper.name,
                offer.price,
                _safe_log(offer.currency, 12),
                product.max_price,
                offer.match_score,
                _safe_log(offer.title, 180),
                _safe_log(offer.url),
            )
            decision = store.decide_alert(
                product_id,
                offer,
                product.max_price,
                settings.alerts.cooldown_hours,
                settings.alerts.notify_back_in_stock,
                persist=not dry_run,
            )
            if decision.should_notify:
                alerts += 1
                stats = store.stats(product_id, offer)
                message = format_alert_message(product, offer, stats)
                if dry_run:
                    LOGGER.info("Mode dry-run, notification non envoyée:\n%s", message)
                else:
                    LOGGER.info("Envoi de la notification Telegram:\n%s", message)
                    if notifier:
                        await notifier.send(product, offer, stats)
        LOGGER.info(
            "Recherche fin produit=%s site=%s extraites=%d correspondantes=%d "
            "sous_seuil=%d alertes=%d",
            _safe_log(product.name, 160),
            scraper.name,
            len(offers),
            matched,
            under_threshold,
            alerts,
        )
    LOGGER.info(
        "Produit fin nom=%s sites_en_échec=%d/%d",
        _safe_log(product.name, 160),
        failures,
        len(scrapers),
    )
    return failures


def cli() -> None:
    parser = argparse.ArgumentParser(description="Surveille les prix de boutiques marocaines")
    parser.add_argument("--settings", type=Path, default=Path("config/settings.yml"))
    parser.add_argument("--products", type=Path, default=Path("config/products.yml"))
    parser.add_argument("--database", type=Path, default=Path("data/prices.db"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(
        asyncio.run(monitor(args.settings, args.products, args.database, args.dry_run))
    )


if __name__ == "__main__":
    cli()
