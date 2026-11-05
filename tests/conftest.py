import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from emporio.config import STORE_TZ  # noqa: E402
from emporio.data import load_store  # noqa: E402
from emporio.policies import PolicyIndex  # noqa: E402
from emporio.session import Session  # noqa: E402
from emporio.tools import Tools  # noqa: E402


@pytest.fixture(scope="session")
def store():
    return load_store()


@pytest.fixture(scope="session")
def policies():
    return PolicyIndex()


@pytest.fixture
def make_tools(store, policies, tmp_path):
    def _make(now="2026-02-20T10:30"):
        clock = lambda: datetime.fromisoformat(now).replace(tzinfo=STORE_TZ)  # noqa: E731
        return Tools(store, policies, Session("test"), clock, tmp_path)

    return _make
