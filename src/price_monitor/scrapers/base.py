from __future__ import annotations

from abc import ABC, abstractmethod

from price_monitor.models import Offer, ProductConfig


class ScraperError(RuntimeError):
    pass


class BaseScraper(ABC):
    @abstractmethod
    async def search(self, product: ProductConfig) -> list[Offer]:
        raise NotImplementedError

    @abstractmethod
    async def aclose(self) -> None:
        raise NotImplementedError
