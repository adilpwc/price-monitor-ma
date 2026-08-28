from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_PRICE = re.compile(r"(?<!\d)(\d[\d\s\u00a0\u202f.,]*\d|\d)(?!\d)")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = re.sub(r"(?<=\w)[\-_/](?=\w)", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def normalized_tokens(value: str) -> set[str]:
    return set(normalize_text(value).split())


def parse_price(value: str) -> Decimal:
    match = _PRICE.search(value.replace("\u00a0", " ").replace("\u202f", " "))
    if not match:
        raise ValueError(f"Prix introuvable: {value!r}")
    raw = re.sub(r"\s", "", match.group(1))
    decimal_sep = next(
        (sep for sep in (",", ".") if sep in raw and len(raw.rsplit(sep, 1)[1]) == 2),
        None,
    )
    if decimal_sep:
        integer, fraction = raw.rsplit(decimal_sep, 1)
        normalized = f"{integer.replace(',', '').replace('.', '')}.{fraction}"
    else:
        normalized = raw.replace(",", "").replace(".", "")
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Prix invalide: {value!r}") from exc
    if result <= 0:
        raise ValueError("Le prix doit être positif")
    return result.quantize(Decimal("0.01"))
