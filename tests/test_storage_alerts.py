from datetime import datetime
from decimal import Decimal
from price_monitor.models import Offer, ProductConfig
from price_monitor.storage import PriceRepository


def offer(price="4399"):
    return Offer("Lenovo", "Lenovo", "UltraPC", Decimal(price), "MAD", True, "https://example.test/p", checked_at=datetime.now().astimezone())


def test_history_and_alert_deduplication(tmp_path):
    repo = PriceRepository(tmp_path / "prices.db")
    repo.initialize()
    product = ProductConfig("Lenovo", Decimal("4500"))
    product_id = repo.upsert_product(product)
    first = offer()
    repo.add_offer(product_id, first)
    assert repo.alert_decision(product_id, product, first, Decimal("2"), Decimal("50")).should_notify
    repo.mark_alerted(product_id, first)
    assert not repo.alert_decision(product_id, product, first, Decimal("2"), Decimal("50")).should_notify
    lower = offer("4300")
    repo.add_offer(product_id, lower)
    assert repo.alert_decision(product_id, product, lower, Decimal("2"), Decimal("50")).should_notify
    stats = repo.stats(product_id, "UltraPC")
    assert stats is not None and stats.previous_price == Decimal("4399")
