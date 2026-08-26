from decimal import Decimal
from price_monitor.models import Offer, ProductConfig
from price_monitor.notifications.telegram import TelegramNotifier


def test_message_contains_price_and_safe_link():
    product = ProductConfig("Lenovo & Legion", Decimal("4500"))
    offer = Offer(product.name, product.name, "UltraPC", Decimal("4399"), "MAD", True, "https://example.test/?a=1&b=2")
    message = TelegramNotifier(token="x", chat_id="y").build_message(product, offer, None)
    assert "4 399 MAD" in message
    assert "Lenovo &amp; Legion" in message
    assert "&amp;" in message
