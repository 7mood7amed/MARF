from datetime import datetime, timedelta, timezone

import pytest

from marf import auth, config


def test_hash_and_verify():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("scrypt$")
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("x", "not-a-hash")


def test_hashes_are_salted():
    assert auth.hash_password("same password 123") != auth.hash_password("same password 123")


def test_create_user_rules(storage):
    with pytest.raises(ValueError):
        auth.create_user(storage, "ab", "long enough password")
    with pytest.raises(ValueError):
        auth.create_user(storage, "has space", "long enough password")
    with pytest.raises(ValueError):
        auth.create_user(storage, "sara", "short")
    with pytest.raises(ValueError):
        auth.create_user(storage, "sara", "long enough password", role="root")
    auth.create_user(storage, "sara", "long enough password")
    with pytest.raises(ValueError):
        auth.create_user(storage, "sara", "long enough password")


def test_password_is_not_stored_in_clear(storage):
    auth.create_user(storage, "sara", "long enough password")
    assert "long enough password" not in storage.get_user("sara")["pw_hash"]


def test_login_success_and_same_message_for_every_failure(storage):
    auth.create_user(storage, "sara", "long enough password", role="admin")
    user, _ = auth.authenticate(storage, "sara", "long enough password")
    assert user == {"username": "sara", "role": "admin"}

    _, wrong_password = auth.authenticate(storage, "sara", "nope nope nope")
    _, unknown_user = auth.authenticate(storage, "nobody", "nope nope nope")
    assert wrong_password == unknown_user == auth.FAILURE_MESSAGE


def test_lockout_after_repeated_failures_then_expires(storage):
    auth.create_user(storage, "sara", "long enough password")
    start = datetime.now(timezone.utc)
    for _ in range(config.MAX_FAILED_LOGINS):
        assert auth.authenticate(storage, "sara", "bad bad bad bad", now=start)[0] is None

    # locked: even the right password is refused
    assert auth.authenticate(storage, "sara", "long enough password", now=start)[0] is None

    later = start + timedelta(minutes=config.LOCKOUT_MINUTES + 1)
    assert auth.authenticate(storage, "sara", "long enough password", now=later)[0] is not None

    actions = [row["action"] for row in storage.list_audit()]
    assert "account_locked" in actions and "login_blocked" in actions


def test_successful_login_resets_the_failure_counter(storage):
    auth.create_user(storage, "sara", "long enough password")
    for _ in range(config.MAX_FAILED_LOGINS - 1):
        auth.authenticate(storage, "sara", "bad bad bad bad")
    assert auth.authenticate(storage, "sara", "long enough password")[0] is not None
    assert storage.get_user("sara")["failed_count"] == 0
