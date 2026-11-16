from __future__ import annotations

import pytest

from app import storage
from app.auth import hash_password
from app.config import Settings
from app.deep_crawl import CrawledPage, DeepCrawlResult
from app.fetcher import FetchResult
from app.jobs import JobRequest, JobRunner


def _page(rows: str) -> str:
    return (
        "<html><body><table><thead><tr><th>名称</th><th>价格</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>"
    )


@pytest.mark.asyncio
async def test_deep_job_merges_pages_and_adds_source_column(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        password_hash=hash_password("x"),
        secret_key=b"k" * 32,
        min_host_interval=0,
        cache_enabled=False,
        max_rows=1000,
    )
    storage.init_db(settings.db_path)
    storage.create_job(
        settings.db_path,
        job_id="job-deep",
        source_type="url",
        url="https://example.com/",
        mode="auto",
        params={},
    )

    async def fake_crawl(*args, **kwargs):
        return DeepCrawlResult(
            pages=[
                CrawledPage(
                    url="https://example.com/",
                    depth=0,
                    result=FetchResult(
                        html=_page("<tr><td>A</td><td>1</td></tr><tr><td>B</td><td>2</td></tr>"),
                        url="https://example.com/",
                        status=200,
                        content_type="text/html",
                        elapsed_ms=5,
                        via="http",
                    ),
                ),
                CrawledPage(
                    url="https://example.com/p2",
                    depth=1,
                    result=FetchResult(
                        html=_page("<tr><td>C</td><td>3</td></tr>"),
                        url="https://example.com/p2",
                        status=200,
                        content_type="text/html",
                        elapsed_ms=4,
                        via="http",
                    ),
                ),
            ],
            discovered=2,
        )

    monkeypatch.setattr("app.jobs.crawl_deep", fake_crawl)
    runner = JobRunner(settings)
    request = JobRequest(
        source="url",
        url="https://example.com/",
        mode="auto",
        deep=True,
        max_links=5,
    )
    extraction, meta = await runner._execute("job-deep", request)

    assert extraction.columns == ["名称", "价格", "来源页面"]
    assert extraction.rows == [
        ["A", "1", "https://example.com/"],
        ["B", "2", "https://example.com/"],
        ["C", "3", "https://example.com/p2"],
    ]
    assert meta["pages_fetched"] == 2
    assert meta["deep"] is True
    assert meta["schema"]["mode"] == "table"
