from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from price_monitor.models import Offer, ProductConfig
from price_monitor.storage import PriceStore


def make_offer(
    *,
    url: str = "https://shop.ma/p/1",
    price: str = "9000",
    available: bool = True,
    hours: int = 0,
) -> Offer:
    return Offer(
        query="MacBook Air M2",
        title="Apple MacBook Air M2",
        site="shop",
        price=Decimal(price),
        currency="MAD",
        available=available,
        url=url,
        checked_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours),
    )


def prepare(path: Path) -> tuple[PriceStore, int]:
    store = PriceStore(path)
    store.sync_products((ProductConfig("MacBook Air M2", Decimal("10000")),))
    return store, store.product_id("MacBook Air M2")


def test_alert_is_scoped_by_url(tmp_path: Path) -> None:
    store, product_id = prepare(tmp_path / "prices.db")
    first = store.decide_alert(product_id, make_offer(), Decimal("10000"), 24, True)
    duplicate = store.decide_alert(product_id, make_offer(hours=1), Decimal("10000"), 24, True)
    second_url = store.decide_alert(
        product_id, make_offer(url="https://shop.ma/p/2", hours=1), Decimal("10000"), 24, True
    )
    assert first.reason == "first_match" and first.should_notify
    assert duplicate.reason == "deduplicated" and not duplicate.should_notify
    assert second_url.reason == "first_match" and second_url.should_notify
    store.close()


def test_back_in_stock_and_price_drop(tmp_path: Path) -> None:
    store, product_id = prepare(tmp_path / "prices.db")
    store.decide_alert(product_id, make_offer(), Decimal("10000"), 24, True)
    unavailable = store.decide_alert(
        product_id, make_offer(available=False, hours=1), Decimal("10000"), 24, True
    )
    back = store.decide_alert(
        product_id, make_offer(price="9500", hours=2), Decimal("10000"), 24, True
    )
    lower = store.decide_alert(
        product_id, make_offer(price="8500", hours=3), Decimal("10000"), 24, True
    )
    assert unavailable.reason == "out_of_stock"
    assert back.reason == "back_in_stock" and back.should_notify
    assert lower.reason == "price_drop" and lower.should_notify
    store.close()


def test_record_stats_and_disable_removed_products(tmp_path: Path) -> None:
    store, product_id = prepare(tmp_path / "prices.db")
    store.record(product_id, make_offer(price="9500"))
    store.record(product_id, make_offer(price="9000", hours=1))
    stats = store.stats(product_id, make_offer(price="9000", hours=1))
    assert stats.previous_price == Decimal("9500")
    assert stats.minimum_price == Decimal("9000")
    store.sync_products(())
    enabled = store.connection.execute("SELECT enabled FROM products").fetchone()[0]
    assert enabled == 0
    store.close()
