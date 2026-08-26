from __future__ import annotations

import html
import os
from decimal import Decimal

import httpx

from ..models import HistoricalStats, Offer, ProductConfig


class TelegramNotifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.client = client or httpx.Client(timeout=15)
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _mad(value: Decimal) -> str:
        return f"{value:,.2f}".replace(",", " ").replace(".00", "") + " MAD"

    def build_message(self, product: ProductConfig, offer: Offer,
                      stats: HistoricalStats | None) -> str:
        saving = product.max_price - offer.price
        lines = [
            "🔥 <b>ALERTE PRIX</b>", html.escape(product.name),
            f"💰 Prix : <b>{self._mad(offer.price)}</b>",
            f"🎯 Seuil : {self._mad(product.max_price)}",
            f"💚 Économie : {self._mad(saving)}", f"🏪 {html.escape(offer.site)}",
        ]
        if stats and stats.previous_price is not None:
            lines.append(f"↕️ Prix précédent : {self._mad(stats.previous_price)}")
        if stats:
            lines.append(f"📉 Minimum historique : {self._mad(stats.minimum_price)}")
        lines.append(f'🔗 <a href="{html.escape(offer.url, quote=True)}">Voir le produit</a>')
        return "\n".join(lines)

    def send(self, message: str) -> None:
        if not self.configured:
            raise RuntimeError("TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID sont requis")
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        response = self.client.post(url, json={
            "chat_id": self.chat_id, "text": message, "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        response.raise_for_status()
