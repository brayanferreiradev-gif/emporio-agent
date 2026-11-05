"""Convert data/store_policies.pdf into data/store_policies.md.

The agent reads the Markdown at runtime (fast, no PDF dependency). The PDF stays in the
repo as the source of truth, and this script keeps the conversion reproducible.

Usage:  python scripts/ingest_policies.py      (needs `pip install pymupdf`)
"""
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data" / "store_policies.pdf"
OUT = ROOT / "data" / "store_policies.md"

HEADER_RE = re.compile(r"^Empório da Música\s+Manual de Políticas e Procedimentos$")
PAGE_RE = re.compile(r"^Página \d+$")
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.{2,80})$")
BULLET_RE = re.compile(r"^[•▪●]\s*")


def page_to_markdown(page) -> list[str]:
    tables = page.find_tables().tables
    items = []  # (y, markdown)
    for t in tables:
        items.append((t.bbox[1], t.to_markdown().replace("<br>", " ")))
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
        if any(t.bbox[1] - 2 <= y0 and y1 <= t.bbox[3] + 2 for t in tables):
            continue  # already rendered as a table
        items.append((y0, text))
    out = []
    for _, block in sorted(items, key=lambda i: i[0]):
        if block.lstrip().startswith("|"):
            out.append(block.strip())
            continue
        # Join wrapped lines; a bullet glyph on its own line starts a new list item.
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        merged = []
        for l in lines:
            if HEADER_RE.match(l) or PAGE_RE.match(l):
                continue
            if BULLET_RE.match(l):
                merged.append("- " + BULLET_RE.sub("", l))
            elif merged and (merged[-1] == "-" or not HEADING_RE.match(l)):
                merged[-1] = (merged[-1] + " " + l).replace("- ", "- ", 1).strip()
            else:
                merged.append(l)
        for l in merged:
            m = HEADING_RE.match(l)
            if m and not l.startswith("-"):
                depth = m.group(1).count(".") + 2
                out.append(f"{'#' * depth} {m.group(1)} {m.group(2)}")
            elif l != "-":
                out.append(l)
    return out


LABEL_RE = re.compile(r"^[A-ZÁÉÍÓÚÂÊÔÇ][\w çãõáéíóúâêôà-]{2,30}:\s")
STRUCTURAL_RE = re.compile(r"^(#|\||- |\d+\.)")


def join_paragraphs(chunks: list[str]) -> list[str]:
    """Re-flow PDF line wraps: a plain line continues the previous paragraph unless it
    starts a new one (heading, table, bullet, numbered step or a 'Label: ...' paragraph)."""
    out: list[str] = []
    for c in chunks:
        c = c.replace("​", "").strip()
        if not c:
            continue
        prev = out[-1] if out else ""
        starts_new = bool(STRUCTURAL_RE.match(c) or LABEL_RE.match(c))
        prev_closed = prev.startswith(("#", "|")) or not prev
        if starts_new or prev_closed:
            out.append(c)
        else:
            out[-1] = prev + " " + c
    return out


def main() -> None:
    doc = pymupdf.open(PDF)
    chunks: list[str] = []
    for page in list(doc)[1:]:  # page 1 is the cover
        chunks += page_to_markdown(page)
    body = join_paragraphs(chunks)
    text = "# Empório da Música — Manual de Políticas e Procedimentos (v2.1)\n\n" + "\n\n".join(body) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT} ({len(body)} blocks)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
