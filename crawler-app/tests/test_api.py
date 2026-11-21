from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import SAMPLE_HTML

PASSWORD = "correct-password"


def login(client: TestClient) -> str:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["csrf"]


def test_requires_login_and_blocks_unauthenticated_api(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        home = client.get("/", follow_redirects=False)
        assert home.status_code == 302
        assert home.headers["location"] == "/login"
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/health").json()["status"] == "ok"


def test_wrong_password_rejected(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/login", json={"password": "nope"})
        assert response.status_code == 401


def test_login_rate_limit(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post("/api/login", json={"password": "nope"}).status_code == 401
        blocked = client.post("/api/login", json={"password": PASSWORD})
        assert blocked.status_code == 429


def test_csrf_required_for_writes(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        login(client)
        response = client.post(
            "/api/jobs",
            json={"source": "html", "html": SAMPLE_HTML, "mode": "table"},
        )
        assert response.status_code == 403


def test_html_job_flow_and_exports(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = login(client)
        headers = {"X-CSRF-Token": csrf}
        assert client.get("/api/me").json()["authenticated"] is True

        analyze = client.post(
            "/api/analyze",
            json={"source": "html", "html": SAMPLE_HTML},
            headers=headers,
        )
        assert analyze.status_code == 200, analyze.text
        assert analyze.json()["tables"][0]["rows"] == 3

        created = client.post(
            "/api/jobs",
            json={"source": "html", "html": SAMPLE_HTML, "mode": "table"},
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
        assert detail["status"] == "done", detail
        assert detail["total_rows"] == 3
        assert detail["columns"] == ["名称", "价格", "库存"]

        csv_response = client.get(f"/api/jobs/{job_id}/export?format=csv")
        assert csv_response.status_code == 200
        assert csv_response.content.startswith(b"\xef\xbb\xbf")

        xlsx_response = client.get(f"/api/jobs/{job_id}/export?format=xlsx")
        assert xlsx_response.status_code == 200
        assert xlsx_response.content[:2] == b"PK"

        md_response = client.get(f"/api/jobs/{job_id}/export?format=md")
        assert md_response.status_code == 200
        assert "| 名称 | 价格 | 库存 |" in md_response.text

        metrics = client.get("/api/metrics")
        assert metrics.status_code == 200
        payload = metrics.json()
        assert payload["cache"]["enabled"] is True
        assert payload["jobs"]["total"] >= 1
        assert payload["version"] == "1.5.0"

        assert client.get(f"/api/jobs/{job_id}/export?format=docx").status_code == 400

        history = client.get("/api/jobs").json()["jobs"]
        assert any(job["id"] == job_id for job in history)

        assert client.delete(f"/api/jobs/{job_id}", headers=headers).status_code == 200
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_css_job_with_html_source(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = login(client)
        created = client.post(
            "/api/jobs",
            json={
                "source": "html",
                "html": SAMPLE_HTML,
                "mode": "css",
                "item_selector": "div.product",
                "fields": [
                    {"name": "标题", "selector": "h2"},
                    {"name": "链接", "selector": "a", "attr": "href"},
                ],
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        detail = {}
        for _ in range(100):
            detail = client.get(f"/api/jobs/{job_id}").json()
            if detail["status"] in {"done", "error"}:
                break
            time.sleep(0.05)
        assert detail["status"] == "done", detail
        assert detail["total_rows"] == 2


def test_ssrf_url_rejected(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = login(client)
        response = client.post(
            "/api/jobs",
            json={"source": "url", "url": "http://169.254.169.254/latest/meta-data", "mode": "table"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 400
        assert "内网" in response.text or "SSRF" in response.text


def test_snapshot_api_from_html_source(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = login(client)
        response = client.post(
            "/api/snapshot",
            json={
                "source": "html",
                "html": SAMPLE_HTML,
                "base_url": "https://example.com/list/",
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["title"] == "示例商品列表"
        assert data["final_url"] == "https://example.com/list/"
        assert data["snapshot_html"].startswith("<!DOCTYPE html>")
        assert '<base href="https://example.com/list/"' in data["snapshot_html"]
        assert data["tables"][0]["headers"] == ["名称", "价格", "库存"]
        assert data["tables"][0]["rule"]["fields"][0]["selector"] == "td:nth-child(1)"
        assert data["detected"]["mode"] in {"table", "css", "article", "structured"}
        assert data["schema"]

