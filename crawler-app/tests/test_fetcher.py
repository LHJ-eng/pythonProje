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
