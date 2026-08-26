from decimal import Decimal
from price_monitor.config import MatchingSettings
from price_monitor.matching import is_match
from price_monitor.models import ProductConfig

SETTINGS = MatchingSettings(72, 0.65, 0.35)
PRODUCT = ProductConfig("Lenovo Legion 27U-10", Decimal("4500"), required_tokens=("lenovo", "legion", "27u", "10"))

def test_compatible_title_matches():
    ok, score = is_match(PRODUCT, "Lenovo Legion 27U 10 écran 27 pouces", SETTINGS)
    assert ok and score >= 72

def test_incompatible_variant_rejected():
    ok, _ = is_match(PRODUCT, "Lenovo Legion 5 Laptop", SETTINGS)
    assert not ok
