"""密码校验、签名会话与登录限流（纯标准库实现，减少攻击面）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from .config import PBKDF2_ITERATIONS


# ---------------------------------------------------------------- 密码哈希
def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iter_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------- 会话令牌
def _sign(secret: bytes, body: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(secret, body, hashlib.sha256).digest()
    ).decode().rstrip("=")


def issue_session(secret: bytes, ttl: int) -> tuple[str, str]:
    """返回 (cookie 值, csrf token)。CSRF 用于所有写操作的双重校验。"""
    payload = {"exp": int(time.time()) + ttl, "csrf": secrets.token_urlsafe(24)}
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode().rstrip("=")
    return f"{body}.{_sign(secret, body.encode())}", payload["csrf"]


def read_session(secret: bytes, token: str | None) -> dict | None:
    """校验签名与过期时间，成功返回 payload，失败返回 None。"""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    if not hmac.compare_digest(_sign(secret, body.encode()), signature):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("exp"), int):
        return None
    if payload["exp"] < int(time.time()):
        return None
    return payload


# ---------------------------------------------------------------- 登录限流
@dataclass
class _Bucket:
    failures: int = 0
    first_failure: float = 0.0
    locked_until: float = 0.0


class LoginRateLimiter:
    """
    按来源 IP 限制登录失败次数，防止在线爆破。
    说明：内存实现，进程重启后清零；多实例部署需换成 Redis 等共享存储。
    """

    def __init__(
        self,
        max_failures: int = 5,
        window: float = 600.0,
        lock_seconds: float = 300.0,
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self.lock_seconds = lock_seconds
        self._buckets: dict[str, _Bucket] = {}

    def locked_for(self, key: str) -> float:
        bucket = self._buckets.get(key)
        if not bucket or bucket.locked_until <= time.time():
            return 0.0
        return bucket.locked_until - time.time()

    def record_failure(self, key: str) -> None:
        now = time.time()
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket.first_failure > self.window:
            bucket = _Bucket(failures=0, first_failure=now)
            self._buckets[key] = bucket
        bucket.failures += 1
        if bucket.failures >= self.max_failures:
            bucket.locked_until = now + self.lock_seconds
            bucket.failures = 0
            bucket.first_failure = now

    def reset(self, key: str) -> None:
        self._buckets.pop(key, None)
