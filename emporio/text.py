"""Small text helpers: accent-insensitive normalisation and a light Portuguese stemmer."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na",
    "nos", "nas", "e", "ou", "com", "sem", "para", "por", "pra", "que", "qual", "quais", "quanto",
    "quanta", "custa", "custando", "preco", "valor", "ate", "ao", "aos", "me", "voce", "voces", "tem",
    "ter", "tenho", "quero", "queria", "gostaria", "saber", "disponivel", "disponiveis", "opcao",
    "opcoes", "r", "rs", "reais", "mais", "menos", "ha", "sao", "esta", "estao", "meu", "minha",
}


def normalize(text: str) -> str:
    """Lowercase, strip accents, turn punctuation into spaces."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def stem(token: str) -> str:
    """Very light plural stripping: violoes -> violao, guitarras -> guitarra."""
    if len(token) > 4 and token.endswith(("oes", "aes")):
        return token[:-3] + "ao"
    if len(token) > 4 and token.endswith("ais"):
        return token[:-3] + "al"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str, drop_stopwords: bool = True) -> list[str]:
    out = []
    for t in normalize(text).split():
        if drop_stopwords and t in STOPWORDS:
            continue
        out.append(stem(t))
    return out


def compact(text: str) -> str:
    """'GD-20' / 'gd 20' -> 'gd20' so model numbers match however they are typed."""
    return normalize(text).replace(" ", "")


def brl(value: float) -> str:
    """Format as Brazilian currency: 5519.08 -> 'R$ 5.519,08'."""
    s = f"{value:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
