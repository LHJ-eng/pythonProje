from __future__ import annotations

import io
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.extractor import (
    detect_text_format,
    extract_auto,
    extract_delimited,
    extract_json_data,
    extract_workbook,
)
from app.fetcher import fetch_url
from app.main import create_app


def _mock_client(monkeypatch, response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)
    monkeypatch.setattr(
        "app.fetcher._client",
        lambda settings: httpx.AsyncClient(transport=transport),
    )
    monkeypatch.setattr("app.fetcher.validate_url", lambda url, allow_private: url)


@pytest.mark.asyncio
async def test_any_suffix_html_is_still_detected(settings, monkeypatch):
    html = b"<!DOCTYPE html><html><body><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>"
    _mock_client(
        monkeypatch,
        httpx.Response(200, content=html, headers={"Content-Type": "text/plain"}),
    )

    result = await fetch_url(
        "https://example.com/report.php?id=1", settings, ignore_robots=True
    )

    assert result.kind == "html"
    assert "<table" in result.html


@pytest.mark.asyncio
async def test_json_endpoint_is_detected_without_suffix(settings, monkeypatch):
    payload = b'{"code": 0, "data": {"list": [{"name": "A", "value": 1}, {"name": "B", "value": 2}, {"name": "C", "value": 3}]}}'
    _mock_client(
        monkeypatch,
        httpx.Response(
            200, content=payload, headers={"Content-Type": "application/json"}
        ),
    )

    result = await fetch_url(
        "https://example.com/api/data", settings, ignore_robots=True
    )

    assert result.kind == "json"
    assert result.html.startswith("{")
    extraction, rule = extract_json_data(result.html, result.url)
    assert rule["mode"] == "json"
    assert len(extraction.rows) == 3
    assert extraction.columns[0] == "名称"


@pytest.mark.asyncio
async def test_csv_download_detected_by_content(settings, monkeypatch):
    body = "名称,数量,日期\n苹果,10,2024-01-01\n香蕉,20,2024-01-02\n橙子,30,2024-01-03\n".encode(
        "utf-8"
    )
    _mock_client(
        monkeypatch,
        httpx.Response(200, content=body, headers={"Content-Type": "application/octet-stream"}),
    )

    result = await fetch_url(
        "https://example.com/export.asp", settings, ignore_robots=True
    )

    assert result.kind == "csv"
    extraction, rule = extract_delimited(result.html, result.url)
    assert rule["mode"] == "csv"
    assert extraction.columns == ["名称", "数量", "日期"]
    assert extraction.rows[0] == ["苹果", "10", "2024-01-01"]


@pytest.mark.asyncio
async def test_xlsx_download_is_parsed(settings, monkeypatch):
    buffer = io.BytesIO()
    book = Workbook()
    sheet = book.active
    sheet.title = "统计"
    sheet.append(["名称", "数量"])
    sheet.append(["苹果", 10])
    sheet.append(["香蕉", 20])
    sheet.append(["橙子", 30])
    book.save(buffer)

    _mock_client(
        monkeypatch,
        httpx.Response(
            200,
            content=buffer.getvalue(),
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
        ),
    )

    result = await fetch_url(
        "https://example.com/export", settings, ignore_robots=True
    )

    assert result.kind == "xlsx"
    extraction, rule = extract_workbook(result.body, result.url)
    assert rule["mode"] == "xlsx"
    assert extraction.columns == ["名称", "数量"]
    assert len(extraction.rows) == 3


def test_detect_text_format_for_pasted_content():
    assert detect_text_format('{"a": 1}') == "json"
    assert detect_text_format("名称\t数量\n苹果\t10\n香蕉\t20") == "csv"
    assert detect_text_format("<table><tr><td>1</td></tr></table>") == "html"


def test_extract_tsv_without_header_uses_generated_columns():
    text = "苹果\t10\n香蕉\t20\n橙子\t30"
    extraction, rule = extract_delimited(text)
    assert rule["mode"] == "csv"
    assert extraction.columns == ["列1", "列2"]
    assert extraction.rows[0] == ["苹果", "10"]


def test_extract_json_matrix_array():
    payload = {
        "result": {
            "values": [
                ["地区", "2023", "2024"],
                ["北京", 100, 120],
                ["上海", 90, 110],
                ["广州", 80, 95],
            ]
        }
    }
    extraction, rule = extract_json_data(payload)
    assert rule["mode"] == "json"
    assert extraction.columns == ["地区", "2023", "2024"]
    assert len(extraction.rows) == 3


def test_extract_auto_detects_div_based_table():
    html = """
    <html><body>
      <div class="grid">
        <div class="row"><span>地区</span><span>产量</span><span>增速</span></div>
        <div class="row"><span>北京</span><span>120</span><span>5.2</span></div>
        <div class="row"><span>上海</span><span>90</span><span>3.1</span></div>
        <div class="row"><span>广州</span><span>80</span><span>2.4</span></div>
      </div>
    </body></html>
    """
    extraction, detected = extract_auto(html, "https://example.com/")
    assert detected["mode"] == "grid"
    assert extraction.columns == ["地区", "产量", "增速"]
    assert len(extraction.rows) == 3


def test_job_with_json_url_uses_auto_detection(settings, monkeypatch):
    from app.fetcher import FetchResult

    async def fake_fetch(url, settings, **kwargs):
        return FetchResult(
            html='{"data": [{"name": "A", "value": 1}, {"name": "B", "value": 2}, {"name": "C", "value": 3}]}',
            url=url,
            status=200,
            content_type="application/json",
            elapsed_ms=1,
            via="http",
            kind="json",
        )

    monkeypatch.setattr("app.jobs.fetch_url", fake_fetch)
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post("/api/login", json={"password": "correct-password"})
        headers = {"X-CSRF-Token": login.json()["csrf"]}
        created = client.post(
            "/api/jobs",
            json={"source": "url", "url": "https://example.com/api.php?list=1"},
            headers=headers,
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        detail = None
        for _ in range(100):
            detail = client.get(f"/api/jobs/{job_id}").json()
            if detail["status"] in {"done", "error"}:
                break
            time.sleep(0.05)

    assert detail is not None
    assert detail["status"] == "done", detail
    assert detail["meta"]["resolved_mode"] == "json"
    assert detail["total_rows"] == 3
    assert detail["columns"] == ["名称", "value"]
