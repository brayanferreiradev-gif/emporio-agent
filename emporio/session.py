"""Conversation session: history persistence + per-customer verification state."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import VAR_DIR

MAX_FAILED_VERIFICATIONS = 3
HISTORY_WINDOW = 24  # messages sent to the model each turn (older ones stay on disk)


def safe_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:60] or "default"


@dataclass
class Session:
    id: str = "default"
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"model", "text": str}]
    verified_customers: list[int] = field(default_factory=list)
    failed_verifications: int = 0

    @property
    def path(self) -> Path:
        return VAR_DIR / "sessions" / f"{safe_id(self.id)}.json"

    def add(self, role: str, text: str, notes: str = "") -> None:
        entry = {"role": role, "text": text}
        if notes:
            entry["notes"] = notes  # internal context for the model (ids seen); never printed
        self.history.append(entry)

    def window(self) -> list[dict]:
        return self.history[-HISTORY_WINDOW:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, session_id: str) -> "Session":
        s = cls(id=session_id)
        if s.path.exists():
            try:
                data = json.loads(s.path.read_text(encoding="utf-8"))
                return cls(**{**asdict(s), **{k: v for k, v in data.items() if k in asdict(s)}})
            except (json.JSONDecodeError, TypeError):
                pass  # corrupted file -> start fresh instead of crashing the chat
        return s

    def reset(self) -> None:
        self.history, self.verified_customers, self.failed_verifications = [], [], 0
        self.path.unlink(missing_ok=True)
