from __future__ import annotations

import sqlite3
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


def test_migrates_v1_database_without_losing_history(tmp_path: Path) -> None:
    database = tmp_path / "prices.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            max_price TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE price_checks (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            site TEXT NOT NULL,
            title TEXT NOT NULL,
            price TEXT NOT NULL,
            currency TEXT NOT NULL,
            available INTEGER NOT NULL,
            url TEXT NOT NULL,
            image_url TEXT,
            match_score REAL NOT NULL,
            checked_at TEXT NOT NULL
        );
        INSERT INTO products(
            name, max_price, enabled, created_at, updated_at
        ) VALUES (
            'Produit historique', '5000', 1, '2025-01-01T00:00:00+00:00',
            '2025-01-01T00:00:00+00:00'
        );
        """
    )
    connection.close()

    store = PriceStore(database)
    store.sync_products((ProductConfig("MacBook Air M2", Decimal("10000")),))
    product_id = store.product_id("MacBook Air M2")
    store.record(product_id, make_offer())

    historical = store.connection.execute(
        "SELECT name FROM products WHERE name='Produit historique'"
    ).fetchone()
    recorded = store.connection.execute(
        "SELECT currency, match_score FROM price_checks WHERE product_id=?", (product_id,)
    ).fetchone()
    timestamps = store.connection.execute(
        "SELECT created_at, updated_at FROM products WHERE id=?", (product_id,)
    ).fetchone()

    assert historical is not None
    assert tuple(recorded) == ("MAD", 0.0)
    assert all(timestamps)
    store.close()
