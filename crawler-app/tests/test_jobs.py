from __future__ import annotations

import sys
import time
import types

from fastapi.testclient import TestClient

from app.extractor import Extraction
from app.fetcher import FetchResult
from app.main import create_app
from app.jobs import JobRequest, sanitize_params


def _login(client: TestClient) -> dict[str, str]:
    response = client.post("/api/login", json={"password": "correct-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf"]}


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        detail = client.get(f"/api/jobs/{job_id}").json()
        if detail["status"] in {"done", "error"}:
            return detail
        time.sleep(0.05)
    raise AssertionError("任务未在预期时间内结束")


def _cards(page: int) -> str:
    return f"""
    <main><div class="products">
      <div class="product"><h2>第{page}页商品 A</h2><span class="price">1.00</span></div>
      <div class="product"><h2>第{page}页商品 B</h2><span class="price">2.00</span></div>
      <div class="product"><h2>第{page}页商品 C</h2><span class="price">3.00</span></div>
    </div></main>
    """


def test_default_auto_reuses_first_page_rule(settings, monkeypatch):
    requested_urls = []

    async def fake_fetch(url, settings, **kwargs):
        requested_urls.append(url)
        page = 1 if url.endswith("/1") else 2
        return FetchResult(
            html=_cards(page), url=url, status=200,
            content_type="text/html", elapsed_ms=1, via="http",
        )

    monkeypatch.setattr("app.jobs.fetch_url", fake_fetch)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={"source": "url", "url": "https://example.com/page/{page}", "pages": 2},
            headers=_login(client),
        )
        assert created.status_code == 202, created.text
        detail = _wait_for_job(client, created.json()["id"])

    assert detail["status"] == "done", detail
    assert detail["mode"] == "auto"
    assert detail["meta"]["resolved_mode"] == "css"
    assert detail["total_rows"] == 6
    assert detail["columns"] == ["标题", "价格"]
    assert detail["rows"][3][0] == "第2页商品 A"
    assert "后续页复用第一页的智能识别规则" in detail["meta"]["warnings"]
    assert requested_urls == [
        "https://example.com/page/1",
        "https://example.com/page/2",
    ]


def test_later_auto_page_failure_keeps_completed_rows(settings, monkeypatch):
    async def fake_fetch(url, settings, **kwargs):
        html = _cards(1) if url.endswith("/1") else "<main><p>没有相同结构</p></main>"
        return FetchResult(
            html=html, url=url, status=200,
            content_type="text/html", elapsed_ms=1, via="http",
        )

    monkeypatch.setattr("app.jobs.fetch_url", fake_fetch)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={"source": "url", "url": "https://example.com/page/{page}", "pages": 2},
            headers=_login(client),
        )
        detail = _wait_for_job(client, created.json()["id"])

    assert detail["status"] == "done", detail
    assert detail["total_rows"] == 3
    assert any("已停止翻页" in warning for warning in detail["meta"]["warnings"])


def test_image_source_validation_and_secret_sanitizing():
    request = JobRequest(
        source="image",
        image_data="data:image/png;base64,c2VjcmV0",
        image_name="table.png",
    )
    stored = sanitize_params(request.model_dump())

    assert request.mode == "auto"
    assert "image_data" not in stored
    assert stored["image_data_chars"] > 0
    assert stored["image_name"] == "table.png"


def _fake_ocr_module(monkeypatch):
    module = types.ModuleType("app.ocr")
    module.decode_image_data = lambda value: b"decoded-image"

    def recognize(data, *, page=1):
        assert data in {b"decoded-image", b"remote-image"}
        return Extraction(
            columns=["页码", "行号", "文字", "置信度", "左", "上", "右", "下"],
            rows=[[str(page), "1", "中文统计表", "0.98", "0", "0", "100", "20"]],
        ), {"engine": "RapidOCR", "average_confidence": 0.98}

    module.recognize_image = recognize
    monkeypatch.setitem(sys.modules, "app.ocr", module)


def test_local_image_job_reuses_history_and_exports(settings, monkeypatch):
    _fake_ocr_module(monkeypatch)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={
                "source": "image",
                "image_data": "data:image/png;base64,c2VjcmV0",
                "image_name": "统计表.png",
            },
            headers=_login(client),
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        detail = _wait_for_job(client, job_id)
        exported = client.get(f"/api/jobs/{job_id}/export?format=csv")

    assert detail["status"] == "done", detail
    assert detail["meta"]["resolved_mode"] == "ocr"
    assert detail["meta"]["image_name"] == "统计表.png"
    assert detail["rows"][0][2] == "中文统计表"
    assert "image_data" not in detail["params"]
    assert exported.status_code == 200
    assert "中文统计表" in exported.content.decode("utf-8-sig")


def test_remote_image_url_auto_switches_to_ocr(settings, monkeypatch):
    _fake_ocr_module(monkeypatch)

    async def fake_fetch(url, settings, **kwargs):
        assert kwargs["allow_image"] is True
        return FetchResult(
            html="", body=b"remote-image", url=url, status=200,
            content_type="image/jpeg", elapsed_ms=1, via="http", kind="image",
        )

    monkeypatch.setattr("app.jobs.fetch_url", fake_fetch)
    app = create_app(settings)
    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={"source": "url", "url": "https://example.com/C02-01.jpg"},
            headers=_login(client),
        )
        detail = _wait_for_job(client, created.json()["id"])

    assert detail["status"] == "done", detail
    assert detail["meta"]["resolved_mode"] == "ocr"
    assert detail["meta"]["auto_detection"]["mode"] == "ocr"
    assert detail["total_rows"] == 1
