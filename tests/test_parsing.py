import pytest
from decimal import Decimal
from price_monitor.parsing import normalize_text, parse_price

@pytest.mark.parametrize(("raw", "expected"), [
    ("4 399 MAD", Decimal("4399.00")),
    ("4\u202f399,00 MAD", Decimal("4399.00")),
    ("4399.00 DH", Decimal("4399.00")),
    ("1.299 MAD", Decimal("1299.00")),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected

def test_normalize_text():
    assert normalize_text("Lenovo Legion 27U-10") == "lenovo legion 27u 10"
