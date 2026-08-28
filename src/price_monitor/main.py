from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .config import Settings, load_products, load_settings
from .models import ProductConfig
from .notifications.telegram import TelegramNotifier
from .scrapers.base import BaseScraper, ScraperError
from .scrapers.html import HtmlScraper
from .storage import PriceStore

LOGGER = logging.getLogger(__name__)


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
    store = PriceStore(database_path)
    store.sync_products(products)
    scrapers = build_scrapers(settings)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    notifier = (
        TelegramNotifier(token, chat_id, settings.http.timeout_seconds)
        if token and chat_id
        else None
    )
    if not dry_run and notifier is None:
        raise RuntimeError(
            "Secrets Telegram absents; utilisez --dry-run pour tester sans notification"
        )

    failures = 0
    try:
        for product in products:
            if not product.enabled:
                continue
            failures += await _monitor_product(
                product, settings, scrapers, store, notifier, dry_run
            )
    finally:
        await asyncio.gather(*(scraper.aclose() for scraper in scrapers))
        if notifier:
            await notifier.aclose()
        store.close()
    return 1 if failures == len(scrapers) * sum(p.enabled for p in products) else 0


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
    for scraper in scrapers:
        try:
            offers = await scraper.search(product)
        except ScraperError as exc:
            failures += 1
            LOGGER.error("%s", exc)
            continue
        for offer in offers:
            store.record(product_id, offer)
            if offer.match_score < 72:
                continue
            decision = store.decide_alert(
                product_id,
                offer,
                product.max_price,
                settings.alerts.cooldown_hours,
                settings.alerts.notify_back_in_stock,
            )
            if decision.should_notify:
                LOGGER.info("Alerte %s: %s", decision.reason, offer.url)
                if notifier and not dry_run:
                    await notifier.send(product, offer, decision.reason)
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
