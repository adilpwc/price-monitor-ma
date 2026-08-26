from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Offer, ProductConfig


class ScraperError(RuntimeError):
    pass


class BaseScraper(ABC):
    name: str

    @abstractmethod
    def search(self, product: ProductConfig) -> list[Offer]:
        raise NotImplementedError
