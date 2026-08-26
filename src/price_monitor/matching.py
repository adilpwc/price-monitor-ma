from __future__ import annotations

from rapidfuzz.fuzz import ratio, token_set_ratio

from .config import MatchingSettings
from .models import ProductConfig
from .parsing import normalize_text


def match_score(query: str, candidate: str, settings: MatchingSettings) -> float:
    q, c = normalize_text(query), normalize_text(candidate)
    return round(
        token_set_ratio(q, c) * settings.token_score_weight
        + ratio(q, c) * settings.ratio_score_weight,
        2,
    )


def is_match(product: ProductConfig, candidate: str, settings: MatchingSettings) -> tuple[bool, float]:
    normalized = normalize_text(candidate)
    tokens = set(normalized.split())
    if product.required_tokens and not all(normalize_text(t) in tokens for t in product.required_tokens):
        return False, 0.0
    if any(normalize_text(t) in tokens for t in product.excluded_tokens):
        return False, 0.0
    scores = [match_score(product.name, candidate, settings)]
    scores.extend(match_score(alias, candidate, settings) for alias in product.aliases)
    score = max(scores)
    return score >= settings.minimum_score, score
