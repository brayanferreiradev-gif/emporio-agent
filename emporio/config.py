"""Runtime configuration: paths, model name and the (simulatable) clock."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
VAR_DIR = ROOT / "var"  # runtime state (sessions, hand-off tickets) — git-ignored
STORE_TZ = ZoneInfo("America/Campo_Grande")

# Free-tier Gemini models are frequently overloaded (503) and older ones get retired for new keys
# (gemini-2.5-flash already returns 404), so the agent walks a chain: first healthy model wins.
DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_FALLBACKS = "gemini-3.5-flash,gemini-3.1-flash-lite"


def thinking_level() -> str:
    return os.getenv("GEMINI_THINKING", "low")


def model_chain() -> list[str]:
    primary = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", DEFAULT_FALLBACKS)
    chain = [primary] + [m.strip() for m in fallbacks.split(",") if m.strip()]
    return list(dict.fromkeys(chain))  # de-duplicate, keep order


def now() -> datetime:
    """Current store-local time.

    The dataset is a frozen snapshot (latest order: 2026-03-22), so ``EMPORIO_NOW``
    (ISO format, e.g. ``2026-03-23T10:30``) lets us simulate a date. Without it the
    real clock is used.
    """
    override = os.getenv("EMPORIO_NOW")
    if override:
        dt = datetime.fromisoformat(override)
        return dt if dt.tzinfo else dt.replace(tzinfo=STORE_TZ)
    return datetime.now(STORE_TZ)
