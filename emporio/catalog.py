"""Catalogue search: accent/plural-insensitive keyword matching with simple field weights.

Deliberately lexical (no embeddings): the catalogue is ~65 items with model numbers
("GD20"), where exact-ish matching beats semantic search, and it needs no extra model.
"""
from __future__ import annotations

import math

from .data import Product, Store
from .text import compact, tokens


def resolve_categories(store: Store, text: str) -> list[int]:
    """Map free text ('violões', 'sopro') to the best-matching category ids."""
    want = set(tokens(text))
    if not want:
        return []
    scored = {cid: len(want & set(tokens(name))) for cid, name in store.categories.items()}
    best = max(scored.values())
    return [cid for cid, s in scored.items() if s == best and best > 0]


def _score(p: Product, q_tokens: list[str], q_compact: str, store: Store) -> float:
    if not q_tokens:
        return 1.0
    name_t, brand_t = set(tokens(p.name, False)), set(tokens(p.brand, False))
    cat_t = set(tokens(p.category, False))
    desc_t = set(tokens(p.description, False))
    spec_t = set(tokens(" ".join(str(v) for v in p.specs.values()), False))
    hits, score = 0, 0.0
    for t in q_tokens:
        w = 3 if t in name_t or t in brand_t else 2 if t in cat_t else 1 if t in desc_t or t in spec_t else 0
        if w:
            hits += 1
            score += w
    if len(q_compact) >= 4 and q_compact in compact(p.name):  # "gd-20" / "gd 20" -> "gd20"
        return score + 10
    return score if hits >= max(1, math.ceil(0.6 * len(q_tokens))) else 0.0


def search(
    store: Store, query: str = "", category: str = "", brand: str = "",
    min_price: float | None = None, max_price: float | None = None,
) -> list[tuple[Product, float]]:
    """Return (product, score) for all matches (any availability), best first."""
    cat_ids = resolve_categories(store, category) if category else []
    extra = "" if (not category or cat_ids) else category  # unknown category -> treat as keywords
    q_tokens = tokens(f"{query} {extra}")
    q_compact = compact(query)
    brand_n = compact(brand)

    out = []
    for p in store.products.values():
        if cat_ids and p.category_id not in cat_ids:
            continue
        if brand_n and brand_n not in compact(p.brand + p.name):
            continue
        if min_price is not None and p.price < min_price:
            continue
        # compare against the price the customer would actually pay (promotion included)
        eff = p.price * (1 - (store.active_promotion(p.id).percent / 100 if store.active_promotion(p.id) else 0))
        if max_price is not None and eff > max_price:
            continue
        s = _score(p, q_tokens, q_compact, store)
        if s > 0:
            out.append((p, s))
    return sorted(out, key=lambda x: (-x[1], x[0].price))


def alternatives(store: Store, p: Product, limit: int = 3) -> list[Product]:
    """Sellable products in the same category, closest in price (for out-of-stock/discontinued)."""
    pool = [x for x in store.products.values() if x.sellable and x.category_id == p.category_id and x.id != p.id]
    return sorted(pool, key=lambda x: abs(x.price - p.price))[:limit]
