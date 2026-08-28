from __future__ import annotations

from decimal import Decimal

from price_monitor.models import HistoricalStats, Offer, ProductConfig
from price_monitor.notifications.telegram import format_alert_message


def test_alert_message_contains_price_savings_and_history() -> None:
    product = ProductConfig("MacBook Air M2", Decimal("17500"))
    offer = Offer(
        query=product.name,
        title="Apple MacBook Air M2 256 Go",
        site="MicroMagma",
        price=Decimal("13127"),
        currency="MAD",
        available=True,
        url="https://micromagma.ma/macbook-air-m2",
    )
    stats = HistoricalStats(
        current_price=offer.price,
        previous_price=Decimal("14000"),
        minimum_price=Decimal("9593"),
        variation=Decimal("-873"),
        last_change_at=None,
    )

    message = format_alert_message(product, offer, stats)

    assert "🔥 <b>ALERTE PRIX</b>" in message
    assert "💰 Prix : <b>13 127 MAD</b>" in message
    assert "🎯 Seuil : 17 500 MAD" in message
    assert "💚 Économie : 4 373 MAD" in message
    assert "🏪 MicroMagma" in message
    assert "📉 Minimum historique : 9 593 MAD" in message
    assert 'href="https://micromagma.ma/macbook-air-m2"' in message


def test_alert_message_escapes_untrusted_html() -> None:
    product = ProductConfig("MacBook <Air>", Decimal("10000"))
    offer = Offer(
        query=product.name,
        title="MacBook <script>",
        site="Shop & Co",
        price=Decimal("9999.90"),
        currency="MAD",
        available=True,
        url="https://shop.ma/p/1?a=1&b=2",
    )
    stats = HistoricalStats(offer.price, None, offer.price, None, None)

    message = format_alert_message(product, offer, stats)

    assert "MacBook &lt;Air&gt;" in message
    assert "9 999,90 MAD" in message
    assert "Shop &amp; Co" in message
    assert "<script>" not in message
    assert "a=1&amp;b=2" in message
