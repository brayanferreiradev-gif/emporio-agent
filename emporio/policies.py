"""Retrieval over the store manual (data/store_policies.md, produced by scripts/ingest_policies.py).

The manual is small (~10 sections), so a transparent BM25 keyword search over
section-level chunks is enough: no vector DB, no embedding calls, easy to debug. A small
synonym table bridges customer vocabulary ("devolver") and manual vocabulary ("devolução").
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR
from .text import tokens

# Known inconsistencies in the manual, resolved to ONE value so the agent never gives two answers.
# (Documented in the README under "Assumptions".)
CANONICAL_FIXES = [
    ("(67) 3321-4500", "(67) 3341-4444"),            # WhatsApp number differs between §1.2 and §7
    ("contato@empóriodamusica.com.br", "contato@emporiodamusica.com.br"),  # accent in e-mail domain
]

# query-word prefix -> extra manual vocabulary
SYNONYMS = {
    ("devol", "arrepend", "troc", "reembols", "estorn", "cancel"): "devolução arrependimento troca reembolso",
    ("fret", "entreg", "envi", "praz", "correi", "motoboy"): "frete entrega prazo",
    ("pag", "parcel", "cart", "pix", "bolet", "credit", "debit", "juros", "vista"): "pagamento parcelamento pix cartão boleto",
    ("horari", "abre", "fecha", "funcion", "abert", "sabad", "doming", "feriad"): "horário funcionamento",
    ("enderec", "local", "onde", "cnpj", "telefon", "whats", "email", "contat"): "empresa dados endereço telefone",
    ("garant", "defeit", "quebr", "estrag", "conserto"): "garantia defeito troca",
    ("promo", "descont", "ofert", "black", "liquid"): "promoções descontos",
    ("acessor", "cord", "palhet", "cabo", "pedal", "amplific", "case"): "acessórios escopo exclusivamente instrumentos",
    ("reclam", "problem", "insatisf"): "reclamação situações especiais",
    ("privac", "lgpd", "exclu", "dado"): "privacidade proteção dados LGPD",
    ("rastre", "codigo", "correio"): "rastreamento código",
}


@dataclass(frozen=True)
class Section:
    ref: str
    title: str
    text: str


def _apply_fixes(text: str) -> str:
    for old, new in CANONICAL_FIXES:
        text = text.replace(old, new)
    return text


def load_sections(path: Path = DATA_DIR / "store_policies.md") -> list[Section]:
    sections: list[Section] = []
    current: list[str] = []
    ref = title = ""

    def flush():
        body = "\n".join(current).strip()
        if title and body:
            sections.append(Section(ref, title, _apply_fixes(body)))

    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#{2,4}\s+(\d+(?:\.\d+)*)\s+(.*)$", line)
        if m:
            flush()
            ref, title, current = m.group(1), m.group(2).strip(), []
        elif title:
            current.append(line)
    flush()
    return sections


class PolicyIndex:
    def __init__(self, sections: list[Section] | None = None):
        self.sections = sections or load_sections()
        # title counts double: headings are the strongest topical signal
        self._docs = [tokens(s.title + " " + s.title + " " + s.text) for s in self.sections]
        self._avg = sum(map(len, self._docs)) / len(self._docs)
        self._df: dict[str, int] = {}
        for d in self._docs:
            for t in set(d):
                self._df[t] = self._df.get(t, 0) + 1

    def _expand(self, query: str) -> list[str]:
        qt = tokens(query)
        raw = query.lower()
        for prefixes, extra in SYNONYMS.items():
            if any(w.startswith(p) for w in raw.split() for p in prefixes):
                qt += tokens(extra)
        return qt

    def search(self, query: str, k: int = 3) -> list[tuple[Section, float]]:
        q = self._expand(query)
        n, scored = len(self._docs), []
        for sec, doc in zip(self.sections, self._docs):
            score = 0.0
            for t in set(q):
                tf = doc.count(t)
                if not tf:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / self._avg))
            if score > 0:
                scored.append((sec, score))
        return sorted(scored, key=lambda x: -x[1])[:k]
