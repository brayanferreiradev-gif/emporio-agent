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

DEFAULT_MODEL = "gemini-2.5-flash"


def model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


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
