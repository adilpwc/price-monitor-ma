from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .models import AlertDecision, HistoricalStats, Offer, ProductConfig

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_checks_product_site_date
  ON price_checks(product_id, site, checked_at DESC);
CREATE TABLE IF NOT EXISTS alert_state (
  product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  site TEXT NOT NULL,
  last_alert_price TEXT NOT NULL,
  last_alert_available INTEGER NOT NULL,
  last_alert_at TEXT NOT NULL,
  PRIMARY KEY(product_id, site)
);
"""


class PriceRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_product(self, product: ProductConfig) -> int:
        now = datetime.now().astimezone().isoformat()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO products(name,max_price,enabled,created_at,updated_at)
                VALUES(?,?,1,?,?) ON CONFLICT(name) DO UPDATE SET
                max_price=excluded.max_price, enabled=1, updated_at=excluded.updated_at""",
                (product.name, str(product.max_price), now, now),
            )
            row = conn.execute("SELECT id FROM products WHERE name=?", (product.name,)).fetchone()
            assert row is not None
            return int(row["id"])

    def add_offer(self, product_id: int, offer: Offer) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO price_checks(product_id,site,title,price,currency,available,url,
                image_url,match_score,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (product_id, offer.site, offer.title, str(offer.price), offer.currency,
                 int(offer.available), offer.url, offer.image_url, offer.match_score,
                 offer.checked_at.isoformat()),
            )

    def stats(self, product_id: int, site: str) -> HistoricalStats | None:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT price,checked_at FROM price_checks WHERE product_id=? AND site=? "
                "ORDER BY checked_at DESC, id DESC", (product_id, site),
            ).fetchall()
        if not rows:
            return None
        current = Decimal(rows[0]["price"])
        previous = Decimal(rows[1]["price"]) if len(rows) > 1 else None
        minimum = min(Decimal(row["price"]) for row in rows)
        last_change = None
        for row in rows[1:]:
            if Decimal(row["price"]) != current:
                last_change = datetime.fromisoformat(rows[0]["checked_at"])
                break
        return HistoricalStats(current, previous, minimum,
                               current - previous if previous is not None else None, last_change)

    def alert_decision(self, product_id: int, product: ProductConfig, offer: Offer,
                       change_percent: Decimal, change_mad: Decimal) -> AlertDecision:
        if not offer.available or offer.price > product.max_price:
            return AlertDecision(False, "hors seuil ou indisponible")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT last_alert_price FROM alert_state WHERE product_id=? AND site=?",
                (product_id, offer.site),
            ).fetchone()
        if row is None:
            return AlertDecision(True, "premier passage sous le seuil")
        old = Decimal(row["last_alert_price"])
        delta = abs(offer.price - old)
        percent = (delta / old * 100) if old else Decimal("100")
        significant = delta >= change_mad or percent >= change_percent
        return AlertDecision(significant, "prix sous seuil modifié" if significant else "alerte identique", old)

    def mark_alerted(self, product_id: int, offer: Offer) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO alert_state(product_id,site,last_alert_price,last_alert_available,last_alert_at)
                VALUES(?,?,?,?,?) ON CONFLICT(product_id,site) DO UPDATE SET
                last_alert_price=excluded.last_alert_price,
                last_alert_available=excluded.last_alert_available,
                last_alert_at=excluded.last_alert_at""",
                (product_id, offer.site, str(offer.price), int(offer.available),
                 datetime.now().astimezone().isoformat()),
            )
