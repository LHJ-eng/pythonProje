from __future__ import annotations

import time

from app.auth import (
    LoginRateLimiter,
    hash_password,
    issue_session,
    read_session,
    verify_password,
)
from app.config import PBKDF2_ITERATIONS

SECRET = b"0123456789abcdef0123456789abcdef"


def test_password_hash_roundtrip():
    encoded = hash_password("s3cret-pass", iterations=1000)
    assert encoded.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret-pass", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("s3cret-pass", "garbage")


def test_default_iterations_are_strong():
    assert PBKDF2_ITERATIONS >= 200_000


def test_session_roundtrip():
    token, csrf = issue_session(SECRET, ttl=60)
    payload = read_session(SECRET, token)
    assert payload is not None
    assert payload["csrf"] == csrf


def test_session_rejects_tampering_and_expiry():
    token, _ = issue_session(SECRET, ttl=60)
    body, signature = token.split(".")
    assert read_session(SECRET, f"{body}x.{signature}") is None
    assert read_session(b"another-secret-key-00000000000000", token) is None
    expired, _ = issue_session(SECRET, ttl=-1)
    assert read_session(SECRET, expired) is None
    assert read_session(SECRET, None) is None


def test_rate_limiter_locks_after_failures():
    limiter = LoginRateLimiter(max_failures=3, window=60, lock_seconds=1)
    for _ in range(3):
        limiter.record_failure("1.2.3.4")
    assert limiter.locked_for("1.2.3.4") > 0
    time.sleep(1.05)
    assert limiter.locked_for("1.2.3.4") == 0
