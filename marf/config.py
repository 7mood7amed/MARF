"""Central configuration. Everything can be overridden with environment variables
(or a .env file next to app.py). See .env.example."""

from __future__ import annotations

import os
from pathlib import Path

try:  # optional: load .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DATA_DIR = Path(os.environ.get("MARF_DATA_DIR", "data")).resolve()
DB_PATH = DATA_DIR / "marf.db"
UPLOAD_DIR = DATA_DIR / "uploads"

MODEL = os.environ.get("MARF_MODEL", "claude-sonnet-5-5")
DEFAULT_CURRENCY = os.environ.get("MARF_CURRENCY", "BHD").upper()
VAT_RATE = os.environ.get("MARF_VAT_RATE", "0.10")  # Bahrain standard rate; change if needed
MAX_UPLOAD_MB = int(os.environ.get("MARF_MAX_UPLOAD_MB", "10"))
RETENTION_DAYS = int(os.environ.get("MARF_RETENTION_DAYS", "90"))
SESSION_MINUTES = int(os.environ.get("MARF_SESSION_MINUTES", "30"))

MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 10
MIN_PASSWORD_LEN = 10


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key or None


def live_mode() -> bool:
    """True when a real API key is configured; otherwise the app runs in demo mode."""
    return api_key() is not None


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
