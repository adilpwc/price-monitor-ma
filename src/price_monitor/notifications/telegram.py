from __future__ import annotations

import html

import httpx

from price_monitor.models import Offer, ProductConfig


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 20) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.client = httpx.AsyncClient(timeout=timeout)

    async def send(self, product: ProductConfig, offer: Offer, reason: str) -> None:
        message = (
            f"🔔 <b>{html.escape(product.name)}</b>\n"
            f"{html.escape(offer.site)} — <b>{offer.price} {html.escape(offer.currency)}</b>\n"
            f"{html.escape(offer.title)}\n"
            f"Motif: {html.escape(reason)}\n"
            f'<a href="{html.escape(offer.url, quote=True)}">Voir l’offre</a>'
        )
        response = await self.client.post(
            self.url,
            json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self.client.aclose()
