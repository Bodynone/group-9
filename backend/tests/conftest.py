from pathlib import Path
import json

import pytest

from backend.config import Settings
from backend.storage import Store


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def samples():
    """Load public synthetic fixtures, never the user's model credentials."""
    expected = json.loads((ROOT / "samples/expected.json").read_text())
    return {
        "S1": (ROOT / "samples/S1.txt").read_text(),
        "S2": (ROOT / "samples/S2.txt").read_text(),
        "expected": expected,
    }


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_key="test-key-not-a-secret",
        base_url="https://model.invalid/v1",
        model="scripted-test-model",
        database_path=str(tmp_path / "tasks.sqlite3"),
        max_model_calls=24,
        task_timeout=300,
        request_timeout=40,
    )


@pytest.fixture
def store(settings):
    storage = Store(settings.database_path)
    yield storage
    storage.close()
