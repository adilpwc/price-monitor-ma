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
    """
    Détermine si un titre de produit correspond au produit recherché.
    
    Utilise le fuzzy matching pour tolérer les variantes orthographiques et réordonnements.
    Les tokens exclus sont vérifiés de façon stricte.
    """
    normalized = normalize_text(candidate)
    
    # Vérifier les exclusions (strict)
    if any(normalize_text(t) in normalized for t in product.excluded_tokens):
        return False, 0.0
    
    # Vérifier les tokens requis avec tolérance
    if product.required_tokens:
        required_normalized = [normalize_text(t) for t in product.required_tokens]
        # Compte les tokens requis trouvés dans le candidat normalisé
        matches = sum(1 for t in required_normalized if t in normalized)
        # Au moins 80% des tokens requis doivent être présents
        if matches < len(required_normalized) * 0.8:
            return False, 0.0
    
    # Calculer le score de correspondance avec fuzzy matching
    scores = [match_score(product.name, candidate, settings)]
    scores.extend(match_score(alias, candidate, settings) for alias in product.aliases)
    score = max(scores)
    
    return score >= settings.minimum_score, score
