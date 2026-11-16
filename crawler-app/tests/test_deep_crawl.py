from __future__ import annotations

import pytest

from app.deep_crawl import (
    compile_pattern,
    crawl_deep,
    discover_links,
    link_allowed,
    parse_sitemap,
)
from app.fetcher import FetchError, FetchResult


def test_link_allowed_filters_domain_assets_and_patterns():
    root = "https://example.com/blog/"
    assert link_allowed("https://example.com/blog/post-1", root)
    assert not link_allowed("https://other.com/blog/post", root)
    assert not link_allowed("https://example.com/logo.png", root)
    assert not link_allowed("https://example.com/files/report.pdf", root)
    assert not link_allowed("mailto:hi@example.com", root)
    assert not link_allowed("https://example.com/blog/app.js", root)

    include = compile_pattern(r"/blog/post-")
    exclude = compile_pattern(r"/tag/")
    assert link_allowed("https://example.com/blog/post-2", root, include=include)
    assert not link_allowed("https://example.com/blog/about", root, include=include)
    assert not link_allowed("https://example.com/blog/tag/x", root, exclude=exclude)


def test_compile_pattern_rejects_invalid_regex():
    with pytest.raises(ValueError, match="正则"):
        compile_pattern("[")


def test_discover_links_dedupes_and_joins():
    html = """
    <a href="/a">A</a>
    <a href="https://example.com/b#frag">B</a>
    <a href="javascript:void(0)">J</a>
    <a href="mailto:a@b.com">M</a>
    <area href="/c">
    """
    links = discover_links(html, "https://example.com/base/")
    assert links == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]


def test_parse_sitemap_decodes_entities():
    xml = (
        '<?xml version="1.0"?><urlset>'
        "<url><loc>https://example.com/x?a=1&amp;b=2</loc></url>"
        "<url><loc>/y</loc></url>"
        "</urlset>"
    )
    assert parse_sitemap(xml, "https://example.com/sitemap.xml") == [
        "https://example.com/x?a=1&b=2",
        "https://example.com/y",
    ]


@pytest.mark.asyncio
async def test_deep_crawl_bfs_respects_limits(settings, monkeypatch):
    pages = {
        "https://example.com/": "<a href='/a'>A</a><a href='/b'>B</a><a href='/c'>C</a>",
        "https://example.com/a": "<p>A</p>",
        "https://example.com/b": "<p>B</p>",
        "https://example.com/c": "<p>C</p>",
    }

    async def fake_fetch(url, settings, **kwargs):
        return FetchResult(
            html=pages[url],
            url=url,
            status=200,
            content_type="text/html",
            elapsed_ms=1,
            via="http",
        )

    monkeypatch.setattr("app.deep_crawl.fetch_url", fake_fetch)
    result = await crawl_deep(
        "https://example.com/",
        settings,
        max_depth=1,
        max_pages=3,
        use_sitemap=False,
        delay=0,
    )
    assert [page.url for page in result.pages] == [
        "https://example.com/",
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert [page.depth for page in result.pages] == [0, 1, 1]
    assert result.truncated is True
    assert result.discovered == 4


@pytest.mark.asyncio
async def test_deep_crawl_depth_zero_only_start(settings, monkeypatch):
    async def fake_fetch(url, settings, **kwargs):
        return FetchResult(
            html="<a href='/a'>A</a>",
            url=url,
            status=200,
            content_type="text/html",
            elapsed_ms=1,
            via="http",
        )

    monkeypatch.setattr("app.deep_crawl.fetch_url", fake_fetch)
    result = await crawl_deep(
        "https://example.com/",
        settings,
        max_depth=0,
        max_pages=5,
        use_sitemap=False,
        delay=0,
    )
    assert [page.url for page in result.pages] == ["https://example.com/"]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_deep_crawl_collects_errors(settings, monkeypatch):
    async def fake_fetch(url, settings, **kwargs):
        raise FetchError("被拒绝")

    monkeypatch.setattr("app.deep_crawl.fetch_url", fake_fetch)
    result = await crawl_deep(
        "https://example.com/",
        settings,
        max_depth=1,
        max_pages=3,
        use_sitemap=False,
        delay=0,
    )
    assert result.pages == []
    assert result.errors and "被拒绝" in result.errors[0]
