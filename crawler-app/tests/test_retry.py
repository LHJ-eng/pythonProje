from __future__ import annotations

import httpx
import pytest

from app.auth import hash_password
from app.config import Settings
from app.fetcher import FetchError, _parse_retry_after, fetch_url


def _settings(tmp_path, **kwargs) -> Settings:
    defaults = dict(
        data_dir=tmp_path,
        password_hash=hash_password("x"),
        secret_key=b"k" * 32,
        min_host_interval=0,
        host_jitter=0,
        cache_enabled=False,
        retry_backoff=0.01,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def test_parse_retry_after_seconds_and_date():
    assert _parse_retry_after("2") == 2
    assert _parse_retry_after("0.5") == 0.5
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("not-a-number") is None
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0


@pytest.mark.asyncio
async def test_retry_on_503_then_success(tmp_path, monkeypatch):
    settings = _settings(tmp_path, max_retries=2)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(
            200, content=b"<html><body>ok</body></html>", headers={"Content-Type": "text/html"}
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)

    result = await fetch_url("https://example.com/retry", settings, ignore_robots=True)
    assert "ok" in result.html
    assert result.retries == 2
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_no_retry_on_404(tmp_path, monkeypatch):
    settings = _settings(tmp_path, max_retries=3)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(404, content=b"missing")

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)

    with pytest.raises(FetchError, match="404"):
        await fetch_url("https://example.com/missing", settings, ignore_robots=True)
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_retry_network_error_then_success(tmp_path, monkeypatch):
    settings = _settings(tmp_path, max_retries=1)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(
            200, content=b"<html><body>ok</body></html>", headers={"Content-Type": "text/html"}
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)

    result = await fetch_url("https://example.com/retry", settings, ignore_robots=True)
    assert result.retries == 1
    assert calls["count"] == 2
