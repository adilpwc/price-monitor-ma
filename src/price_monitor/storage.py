from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .models import AlertDecision, HistoricalStats, Offer, ProductConfig


class PriceStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                max_price TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS price_checks (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id),
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                price TEXT NOT NULL,
                currency TEXT NOT NULL,
                available INTEGER NOT NULL,
                image_url TEXT,
                match_score REAL NOT NULL,
                checked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_checks_offer
                ON price_checks(product_id, site, url, checked_at DESC);
            CREATE TABLE IF NOT EXISTS alert_state_v2 (
                product_id INTEGER NOT NULL REFERENCES products(id),
                site TEXT NOT NULL,
                url TEXT NOT NULL,
                last_alert_price TEXT,
                last_alert_at TEXT,
                last_available INTEGER NOT NULL,
                PRIMARY KEY(product_id, site, url)
            );
            """
        )
        self._migrate_schema()
        self.connection.commit()

    def _columns(self, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in self.connection.execute(f"PRAGMA table_info({table})")  # noqa: S608
        }

    def _migrate_schema(self) -> None:
        """Make v1 and early v2 databases compatible without deleting their history."""
        product_columns = self._columns("products")
        if "created_at" not in product_columns:
            self.connection.execute("ALTER TABLE products ADD COLUMN created_at TEXT")
        if "updated_at" not in product_columns:
            self.connection.execute("ALTER TABLE products ADD COLUMN updated_at TEXT")

        check_columns = self._columns("price_checks")
        if "currency" not in check_columns:
            self.connection.execute(
                "ALTER TABLE price_checks ADD COLUMN currency TEXT NOT NULL DEFAULT 'MAD'"
            )
        if "image_url" not in check_columns:
            self.connection.execute("ALTER TABLE price_checks ADD COLUMN image_url TEXT")
        if "match_score" not in check_columns:
            self.connection.execute(
                "ALTER TABLE price_checks ADD COLUMN match_score REAL NOT NULL DEFAULT 0"
            )

    def sync_products(self, products: tuple[ProductConfig, ...]) -> None:
        active_names = {product.name for product in products if product.enabled}
        now = datetime.now(UTC).isoformat()
        for product in products:
            self.connection.execute(
                """INSERT INTO products(
                       name, max_price, enabled, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                       max_price=excluded.max_price,
                       enabled=excluded.enabled,
                       updated_at=excluded.updated_at""",
                (product.name, str(product.max_price), int(product.enabled), now, now),
            )
        if active_names:
            placeholders = ",".join("?" for _ in active_names)
            self.connection.execute(
                f"UPDATE products SET enabled=0 WHERE name NOT IN ({placeholders})",  # noqa: S608
                tuple(active_names),
            )
        else:
            self.connection.execute("UPDATE products SET enabled=0")
        self.connection.commit()

    def product_id(self, name: str) -> int:
        row = self.connection.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
        if row is None:
            raise KeyError(f"Produit inconnu: {name}")
        return int(row["id"])

    def record(self, product_id: int, offer: Offer) -> None:
        self.connection.execute(
            """INSERT INTO price_checks(
                   product_id, site, url, title, price, currency, available,
                   image_url, match_score, checked_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                product_id,
                offer.site,
                offer.url,
                offer.title,
                str(offer.price),
                offer.currency,
                int(offer.available),
                offer.image_url,
                offer.match_score,
                offer.checked_at.astimezone(UTC).isoformat(),
            ),
        )
        self.connection.commit()

    def decide_alert(
        self,
        product_id: int,
        offer: Offer,
        threshold: Decimal,
        cooldown_hours: int,
        notify_back_in_stock: bool,
    ) -> AlertDecision:
        row = self.connection.execute(
            """SELECT last_alert_price, last_alert_at, last_available
               FROM alert_state_v2 WHERE product_id=? AND site=? AND url=?""",
            (product_id, offer.site, offer.url),
        ).fetchone()
        previous_available = bool(row["last_available"]) if row else None
        previous_price = (
            Decimal(row["last_alert_price"]) if row and row["last_alert_price"] else None
        )
        last_alert_at = (
            datetime.fromisoformat(row["last_alert_at"])
            if row and row["last_alert_at"]
            else None
        )
        now = offer.checked_at.astimezone(UTC)
        back_in_stock = previous_available is False and offer.available
        under_threshold = offer.available and offer.price <= threshold
        cheaper = previous_price is not None and offer.price < previous_price
        cooldown_elapsed = last_alert_at is None or now - last_alert_at >= timedelta(
            hours=cooldown_hours
        )

        should_notify = under_threshold and (
            previous_price is None
            or cheaper
            or cooldown_elapsed
            or (notify_back_in_stock and back_in_stock)
        )
        if not offer.available:
            reason = "out_of_stock"
        elif offer.price > threshold:
            reason = "above_threshold"
        elif notify_back_in_stock and back_in_stock:
            reason = "back_in_stock"
        elif previous_price is None:
            reason = "first_match"
        elif cheaper:
            reason = "price_drop"
        elif cooldown_elapsed:
            reason = "cooldown_elapsed"
        else:
            reason = "deduplicated"

        self.connection.execute(
            """INSERT INTO alert_state_v2(
                   product_id, site, url, last_alert_price, last_alert_at, last_available
               ) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(product_id, site, url) DO UPDATE SET
                   last_alert_price=CASE WHEN excluded.last_alert_at IS NOT NULL
                                         THEN excluded.last_alert_price
                                         ELSE alert_state_v2.last_alert_price END,
                   last_alert_at=COALESCE(excluded.last_alert_at, alert_state_v2.last_alert_at),
                   last_available=excluded.last_available""",
            (
                product_id,
                offer.site,
                offer.url,
                str(offer.price) if should_notify else None,
                now.isoformat() if should_notify else None,
                int(offer.available),
            ),
        )
        self.connection.commit()
        return AlertDecision(should_notify, reason, previous_price)

    def stats(self, product_id: int, offer: Offer) -> HistoricalStats:
        rows = self.connection.execute(
            """SELECT price, checked_at FROM price_checks
               WHERE product_id=? AND site=? AND url=? AND available=1
               ORDER BY checked_at DESC""",
            (product_id, offer.site, offer.url),
        ).fetchall()
        prices = [Decimal(row["price"]) for row in rows]
        previous = prices[1] if len(prices) > 1 else None
        return HistoricalStats(
            current_price=offer.price,
            previous_price=previous,
            minimum_price=min(prices, default=offer.price),
            variation=offer.price - previous if previous is not None else None,
            last_change_at=None,
        )

    def close(self) -> None:
        self.connection.close()
