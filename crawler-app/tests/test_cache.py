from __future__ import annotations

import httpx
import pytest

from app.auth import hash_password
from app.cache import HttpCache
from app.config import Settings
from app.fetcher import fetch_url


def _settings(tmp_path, **kwargs) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        password_hash=hash_password("x"),
        secret_key=b"k" * 32,
        min_host_interval=0,
        max_retries=0,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def test_cache_put_get_and_validators(tmp_path):
    cache = HttpCache(tmp_path / "cache.db", ttl=60)
    cache.put(
        "https://example.com/a",
        status=200,
        content_type="text/html; charset=utf-8",
        body=b"<html>hello</html>",
        etag='"v1"',
        last_modified="Wed, 21 Oct 2015 07:28:00 GMT",
    )

    entry = cache.get("https://example.com/a")
    assert entry is not None
    assert entry.body == b"<html>hello</html>"
    assert entry.expired is False
    assert entry.validators() == {
        "If-None-Match": '"v1"',
        "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT",
    }
    assert cache.get("https://example.com/missing") is None
    stats = cache.stats()
    assert stats["entries"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_cache_ttl_zero_is_expired(tmp_path):
    cache = HttpCache(tmp_path / "cache.db", ttl=0)
    cache.put(
        "https://example.com/a", status=200, content_type="text/html", body=b"x"
    )
    entry = cache.get("https://example.com/a")
    assert entry is not None and entry.expired is True


def test_cache_eviction_keeps_limits(tmp_path):
    cache = HttpCache(tmp_path / "cache.db", ttl=60, max_entries=2, max_bytes=10_000)
    for index in range(4):
        cache.put(
            f"https://example.com/{index}",
            status=200,
            content_type="text/html",
            body=b"x" * 10,
        )
    assert cache.stats()["entries"] <= 2


@pytest.mark.asyncio
async def test_fetch_uses_cache_and_revalidates_etag(tmp_path, monkeypatch):
    settings = _settings(tmp_path, cache_ttl=0)
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"ETag": '"v1"'})
        return httpx.Response(
            200,
            content=b"<html><body>cached page</body></html>",
            headers={
                "Content-Type": "text/html; charset=utf-8",
                "ETag": '"v1"',
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)

    first = await fetch_url("https://example.com/a", settings, ignore_robots=True)
    assert "cached page" in first.html
    assert first.from_cache is False

    second = await fetch_url("https://example.com/a", settings, ignore_robots=True)
    assert second.from_cache is True
    assert second.via == "cache-revalidated"
    assert "cached page" in second.html
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_fetch_serves_fresh_cache_and_bypass(tmp_path, monkeypatch):
    settings = _settings(tmp_path, cache_ttl=600)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            content=b"<html><body>fresh</body></html>",
            headers={"Content-Type": "text/html"},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)

    await fetch_url("https://example.com/fresh", settings, ignore_robots=True)
    cached = await fetch_url("https://example.com/fresh", settings, ignore_robots=True)
    assert cached.from_cache is True
    assert cached.via == "cache"
    assert calls["count"] == 1

    bypassed = await fetch_url(
        "https://example.com/fresh",
        settings,
        ignore_robots=True,
        cache_mode="bypass",
    )
    assert bypassed.from_cache is False
    assert calls["count"] == 2
