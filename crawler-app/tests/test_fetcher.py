from __future__ import annotations

import httpx
import pytest

from app.fetcher import FetchError, fetch_url


def _mock_client(monkeypatch, response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)


@pytest.mark.asyncio
async def test_fetch_auto_returns_original_image_bytes(settings, monkeypatch):
    image = b"\xff\xd8\xff\xe0" + b"jpeg-data" + b"\xff\xd9"
    _mock_client(monkeypatch, httpx.Response(200, content=image, headers={"Content-Type": "image/jpeg"}))

    result = await fetch_url(
        "https://example.com/table.jpg", settings,
        ignore_robots=True, allow_image=True,
    )

    assert result.kind == "image"
    assert result.body == image
    assert result.html == ""


@pytest.mark.asyncio
async def test_fetch_detects_image_magic_without_image_content_type(settings, monkeypatch):
    image = b"\x89PNG\r\n\x1a\n" + b"png-data"
    _mock_client(monkeypatch, httpx.Response(200, content=image, headers={"Content-Type": "application/octet-stream"}))

    result = await fetch_url(
        "https://example.com/download", settings,
        ignore_robots=True, allow_image=True,
    )

    assert result.kind == "image"
    assert result.body == image


@pytest.mark.asyncio
async def test_manual_fetch_still_rejects_image(settings, monkeypatch):
    _mock_client(monkeypatch, httpx.Response(200, content=b"\xff\xd8\xff\xe0", headers={"Content-Type": "image/jpeg"}))

    with pytest.raises(FetchError, match="不是 HTML"):
        await fetch_url(
            "https://example.com/table.jpg", settings,
            ignore_robots=True, allow_image=False,
        )


@pytest.mark.asyncio
async def test_fetch_detects_rss_feed(settings, monkeypatch):
    rss = b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>A</title></item></channel></rss>'
    _mock_client(
        monkeypatch,
        httpx.Response(200, content=rss, headers={"Content-Type": "application/rss+xml"}),
    )

    result = await fetch_url(
        "https://example.com/feed", settings, ignore_robots=True, allow_image=True
    )

    assert result.kind == "feed"
    assert "<rss" in result.html


@pytest.mark.asyncio
async def test_fetch_detects_atom_feed_by_body(settings, monkeypatch):
    atom = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title></entry></feed>'
    _mock_client(
        monkeypatch,
        httpx.Response(200, content=atom, headers={"Content-Type": "application/octet-stream"}),
    )

    result = await fetch_url(
        "https://example.com/atom", settings, ignore_robots=True, allow_image=True
    )

    assert result.kind == "feed"
