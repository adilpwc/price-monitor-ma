from __future__ import annotations

import html
from decimal import Decimal

import httpx

from price_monitor.models import HistoricalStats, Offer, ProductConfig


def _format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    if quantized == quantized.to_integral():
        return f"{int(quantized):,}".replace(",", " ")
    integer, decimals = f"{quantized:.2f}".split(".")
    return f"{int(integer):,}".replace(",", " ") + f",{decimals}"


def format_alert_message(
    product: ProductConfig,
    offer: Offer,
    stats: HistoricalStats,
) -> str:
    currency = html.escape(offer.currency)
    economy = max(product.max_price - offer.price, Decimal("0"))
    return (
        "🔥 <b>ALERTE PRIX</b>\n"
        f"{html.escape(product.name)}\n"
        f"💰 Prix : <b>{_format_amount(offer.price)} {currency}</b>\n"
        f"🎯 Seuil : {_format_amount(product.max_price)} {currency}\n"
        f"💚 Économie : {_format_amount(economy)} {currency}\n"
        f"🏪 {html.escape(offer.site)}\n"
        f"📉 Minimum historique : {_format_amount(stats.minimum_price)} {currency}\n"
        f"📦 {html.escape(offer.title)}\n"
        f'<a href="{html.escape(offer.url, quote=True)}">Voir l’offre</a>'
    )


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 20) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = httpx.AsyncClient(timeout=timeout)

    async def send(
        self,
        product: ProductConfig,
        offer: Offer,
        stats: HistoricalStats,
    ) -> None:
        response = await self.client.post(
            self.url,
            json={
                "chat_id": self.chat_id,
                "text": format_alert_message(product, offer, stats),
                "parse_mode": "HTML",
            },
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self.client.aclose()
