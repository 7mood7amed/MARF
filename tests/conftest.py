import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from marf.storage import Storage  # noqa: E402

SAMPLES = ROOT / "samples"


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    """Tests never call the real API: with no key, extraction reads samples/expected.json."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "marf.db", tmp_path / "uploads")


@pytest.fixture
def sample():
    def load(name: str) -> bytes:
        return (SAMPLES / name).read_bytes()

    return load
