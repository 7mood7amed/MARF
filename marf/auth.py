"""Password hashing (scrypt), login with lockout, and user creation."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from . import config
from .storage import Storage

_N, _R, _P = 2**14, 8, 1
ROLES = ("admin", "user")
FAILURE_MESSAGE = "Invalid username or password, or the account is temporarily locked."


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        candidate = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)


_DUMMY_HASH = hash_password("not-a-real-password")  # keeps timing similar for unknown usernames


def create_user(storage: Storage, username: str, password: str, role: str = "user") -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""):
        raise ValueError("Username must be 3-32 characters: letters, digits, dot, dash or underscore.")
    if len(password or "") < config.MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {config.MIN_PASSWORD_LEN} characters.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    try:
        storage.add_user(username, hash_password(password), role)
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username already exists.") from exc
    storage.log(username, "user_created", f"role={role}")


def authenticate(storage: Storage, username: str, password: str, now: datetime | None = None) -> tuple[dict | None, str]:
    """Returns (user, message). Every failure gives the same message so usernames can't be probed."""
    now = now or datetime.now(timezone.utc)
    user = storage.get_user(username)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None, FAILURE_MESSAGE

    locked_until = user["locked_until"]
    if locked_until and datetime.fromisoformat(locked_until) > now:
        storage.log(username, "login_blocked", "account locked")
        return None, FAILURE_MESSAGE

    if verify_password(password, user["pw_hash"]):
        storage.set_login_state(username, 0, None)
        storage.log(username, "login")
        return {"username": user["username"], "role": user["role"]}, ""

    failed = user["failed_count"] + 1
    if failed >= config.MAX_FAILED_LOGINS:
        until = (now + timedelta(minutes=config.LOCKOUT_MINUTES)).isoformat(timespec="seconds")
        storage.set_login_state(username, 0, until)
        storage.log(username, "account_locked", f"after {failed} failed attempts")
    else:
        storage.set_login_state(username, failed, None)
        storage.log(username, "login_failed", f"attempt {failed}")
    return None, FAILURE_MESSAGE
