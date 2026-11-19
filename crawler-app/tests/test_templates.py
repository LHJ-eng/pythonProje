from __future__ import annotations

from fastapi.testclient import TestClient

from app import storage
from app.main import create_app

PASSWORD = "correct-password"
RULE = {
    "mode": "css",
    "item_selector": "ul.items > li.item",
    "item_selector_type": "css",
    "fields": [
        {"name": "标题", "selector": "h3", "attr": "text", "selector_type": "css"},
        {"name": "链接", "selector": "a", "attr": "href", "selector_type": "css"},
    ],
}


def login(client: TestClient) -> str:
    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["csrf"]


def test_template_storage_crud(settings):
    storage.init_db(settings.db_path)
    created = storage.save_template(
        settings.db_path,
        name="列表模板",
        rule=RULE,
        source_url="https://example.com/list",
    )
    assert created["id"]
    assert created["rule"]["fields"][0]["name"] == "标题"
    assert storage.list_templates(settings.db_path)[0]["id"] == created["id"]

    updated = storage.save_template(
        settings.db_path,
        name="列表模板（新）",
        rule=RULE,
        template_id=created["id"],
    )
    assert updated["name"] == "列表模板（新）"
    assert updated["updated_at"] >= created["updated_at"]

    assert storage.delete_template(settings.db_path, created["id"]) is True
    assert storage.get_template(settings.db_path, created["id"]) is None
    assert storage.delete_template(settings.db_path, "missing") is False


def test_templates_api_flow(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        csrf = login(client)
        headers = {"X-CSRF-Token": csrf}

        assert client.get("/api/templates").json()["templates"] == []

        created = client.post(
            "/api/templates",
            json={
                "name": "商品列表",
                "description": "测试模板",
                "source_url": "https://example.com/list",
                "rule": RULE,
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        template = created.json()
        assert template["name"] == "商品列表"
        assert template["rule"]["mode"] == "css"

        listed = client.get("/api/templates").json()["templates"]
        assert len(listed) == 1

        too_long = client.post(
            "/api/templates",
            json={
                "name": "非法",
                "rule": {"mode": "css", "item_selector": "li", "fields": []},
            },
            headers=headers,
        )
        assert too_long.status_code == 400

        deleted = client.delete(f"/api/templates/{template['id']}", headers=headers)
        assert deleted.status_code == 200
        assert client.delete(
            f"/api/templates/{template['id']}", headers=headers
        ).status_code == 404
