from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from pathlib import Path

from price_monitor.config import load_settings
from price_monitor.main import _monitor_product
from price_monitor.models import Offer, ProductConfig
from price_monitor.scrapers.base import BaseScraper
from price_monitor.storage import PriceStore


class ThresholdScraper(BaseScraper):
    @property
    def name(self) -> str:
        return "threshold-shop"

    async def search(self, product: ProductConfig) -> list[Offer]:
        return [
            Offer(
                query=product.name,
                title="MacBook Air M2 au seuil",
                site=self.name,
                price=Decimal("10000"),
                currency="MAD",
                available=True,
                url="https://shop.ma/equal",
                match_score=100,
            ),
            Offer(
                query=product.name,
                title="MacBook Air M2 au-dessus du seuil",
                site=self.name,
                price=Decimal("10000.01"),
                currency="MAD",
                available=True,
                url="https://shop.ma/above",
                match_score=100,
            ),
        ]

    async def aclose(self) -> None:
        return None


def test_only_equal_or_lower_prices_are_displayed_and_alerted(
    tmp_path: Path,
    caplog,
) -> None:
    product = ProductConfig("MacBook Air M2", Decimal("10000"))
    settings = load_settings(Path("config/settings.yml"))
    store = PriceStore(tmp_path / "prices.db")
    store.sync_products((product,))

    with caplog.at_level(logging.INFO):
        failures = asyncio.run(
            _monitor_product(
                product,
                settings,
                [ThresholdScraper()],
                store,
                notifier=None,
                dry_run=True,
            )
        )

    assert failures == 0
    assert "Offre sous seuil site=threshold-shop prix=10000 MAD seuil=10000" in caplog.text
    assert "🔥 <b>ALERTE PRIX</b>" in caplog.text
    assert "10000.01" not in caplog.text
    assert "sous_seuil=1 alertes=1" in caplog.text
    store.close()
