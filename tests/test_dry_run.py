from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from price_monitor.models import Offer, ProductConfig
from price_monitor.storage import PriceStore


def test_dry_run_decision_does_not_persist_alert_state(tmp_path) -> None:
    store = PriceStore(tmp_path / "prices.db")
    product = ProductConfig("MacBook Air M2", Decimal("10000"))
    store.sync_products((product,))
    product_id = store.product_id(product.name)
    offer = Offer(
        query=product.name,
        title="Apple MacBook Air M2",
        site="shop",
        price=Decimal("9000"),
        currency="MAD",
        available=True,
        url="https://shop.ma/p/1",
        checked_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    decision = store.decide_alert(
        product_id,
        offer,
        product.max_price,
        cooldown_hours=24,
        notify_back_in_stock=True,
        persist=False,
    )
    rows = store.connection.execute("SELECT COUNT(*) FROM alert_state_v2").fetchone()[0]

    assert decision.should_notify
    assert decision.reason == "first_match"
    assert rows == 0
    store.close()
