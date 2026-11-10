from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_store import DataStore  # noqa: E402
from src.engine import RulesEngine  # noqa: E402


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def data() -> DataStore:
    return DataStore.load(ROOT / "data")


@pytest.fixture(scope="session")
def engine(data: DataStore) -> RulesEngine:
    return RulesEngine(data)


@pytest.fixture(scope="session")
def inbox_tickets() -> list[dict]:
    return load_json("tickets/support_inbox_export.json")


@pytest.fixture(scope="session")
def public_tickets() -> list[dict]:
    return load_json("inbox/public_tickets.json")


@pytest.fixture(scope="session")
def labels() -> list[dict]:
    return load_json("tickets/eval_seed_labelled.json")
