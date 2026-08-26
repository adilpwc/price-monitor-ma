from decimal import Decimal
from pathlib import Path
from price_monitor.config import HttpSettings, MatchingSettings, ScraperSettings
from price_monitor.models import ProductConfig
from price_monitor.scrapers.ultrapc import UltraPCScraper


def test_parse_ultrapc_fixture():
    scraper = UltraPCScraper(
        ScraperSettings(True, "https://www.ultrapc.ma", "/recherche", "s", 20),
        HttpSettings(20, 10, 0, 1, 0, "tests"),
        MatchingSettings(72, .65, .35),
    )
    try:
        html = Path("tests/fixtures/ultrapc_search.html").read_text(encoding="utf-8")
        product = ProductConfig("Lenovo Legion 27U-10", Decimal("4500"), required_tokens=("lenovo", "legion", "27u", "10"))
        offers = scraper.parse_html(html, product)
        assert len(offers) == 1
        assert offers[0].price == Decimal("4399.00")
        assert offers[0].available is True
        assert offers[0].url.startswith("https://www.ultrapc.ma/")
    finally:
        scraper.close()
