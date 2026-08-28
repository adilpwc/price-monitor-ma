from __future__ import annotations

from difflib import SequenceMatcher

from .models import ProductConfig
from .parsing import normalize_text, normalized_tokens


def match_score(product: ProductConfig, title: str) -> float:
    title_normalized = normalize_text(title)
    title_tokens = normalized_tokens(title)
    excluded = {normalize_text(token) for token in product.excluded_tokens}
    required = {normalize_text(token) for token in product.required_tokens}
    if excluded & title_tokens or not required.issubset(title_tokens):
        return 0.0

    scores: list[float] = []
    for candidate in (product.name, *product.aliases):
        candidate_normalized = normalize_text(candidate)
        candidate_tokens = normalized_tokens(candidate)
        token_coverage = len(candidate_tokens & title_tokens) / max(len(candidate_tokens), 1)
        sequence_ratio = SequenceMatcher(None, candidate_normalized, title_normalized).ratio()
        scores.append((0.65 * token_coverage + 0.35 * sequence_ratio) * 100)
    return max(scores)
