from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.exporter import to_markdown
from app.extractor import (
    Extraction,
    ExtractionError,
    build_schema,
    extract_auto,
    extract_css,
    normalize_rule,
)
from app.jobs import JobRequest

XPATH_HTML = """<html><body><ul>
  <li class="row"><span class="n">A</span><a href="/a">详情</a></li>
  <li class="row"><span class="n">B</span><a href="/b">详情</a></li>
</ul></body></html>"""


def test_xpath_item_and_fields():
    extraction = extract_css(
        XPATH_HTML,
        "https://example.com/",
        "//li[@class='row']",
        [
            {"name": "名称", "selector": ".//span[@class='n']", "attr": "text"},
            {"name": "链接", "selector": ".//a", "attr": "href"},
        ],
        item_selector_type="xpath",
    )
    assert extraction.columns == ["名称", "链接"]
    assert extraction.rows == [
        ["A", "https://example.com/a"],
        ["B", "https://example.com/b"],
    ]


def test_xpath_field_inside_css_item():
    extraction = extract_css(
        XPATH_HTML,
        "https://example.com/",
        "li.row",
        [
            {
                "name": "名称",
                "selector": ".//span[@class='n']/text()",
                "attr": "text",
                "selector_type": "xpath",
            }
        ],
        item_selector_type="css",
    )
    assert extraction.rows == [["A"], ["B"]]


def test_css_item_with_xpath_text_node():
    extraction = extract_css(
        XPATH_HTML,
        "https://example.com/",
        "//li[@class='row']",
        [{"name": "名称", "selector": ".//span[@class='n']/text()"}],
        item_selector_type="xpath",
    )
    assert extraction.rows == [["A"], ["B"]]


def test_normalize_rule_validates_structure():
    with pytest.raises(ExtractionError):
        normalize_rule({"mode": "hack"})
    with pytest.raises(ExtractionError):
        normalize_rule({"mode": "css", "item_selector": "", "fields": []})
    with pytest.raises(ExtractionError):
        normalize_rule(
            {
                "mode": "css",
                "item_selector": "li",
                "fields": [{"name": "", "selector": "h2"}],
            }
        )

    normalized = normalize_rule(
        {
            "mode": "css",
            "item_selector": "li",
            "item_selector_type": "xpath",
            "fields": [{"name": "标题", "selector": ".//h2", "selector_type": "xpath"}],
        }
    )
    assert normalized is not None
    assert normalized["item_selector_type"] == "xpath"
    assert normalized["fields"][0]["selector_type"] == "xpath"


def test_build_schema_roundtrip():
    extraction = extract_css(
        XPATH_HTML,
        "https://example.com/",
        "li.row",
        [{"name": "名称", "selector": "span.n"}],
    )
    detected = {
        "mode": "css",
        "item_selector": "li.row",
        "item_selector_type": "css",
        "fields": [{"name": "名称", "selector": "span.n", "attr": "text"}],
    }
    schema = build_schema(extraction, detected, source_url="https://example.com/")
    assert schema["version"] == 1
    assert schema["source_url"] == "https://example.com/"
    assert schema["fields"][0]["name"] == "名称"

    normalized = normalize_rule(schema)
    assert normalized is not None
    assert normalized == detected | {"fields": [normalized["fields"][0]]}


def test_markdown_export_escapes_pipes():
    payload = to_markdown(
        ["名称", "价格"],
        [["A|B", "9.9"]],
        {"source_url": "https://example.com/"},
    )
    text = payload.decode("utf-8")
    assert "| 名称 | 价格 |" in text
    assert "A\\|B" in text
    assert "https://example.com/" in text


def test_job_request_accepts_validated_rule():
    rule = {
        "mode": "css",
        "item_selector": "li.row",
        "fields": [{"name": "名称", "selector": "span.n"}],
    }
    request = JobRequest(
        source="url", url="https://example.com/", mode="auto", rule=rule
    )
    assert request.rule is not None
    assert request.rule["item_selector"] == "li.row"

    with pytest.raises(ValidationError):
        JobRequest(
            source="url",
            url="https://example.com/",
            mode="auto",
            rule={"mode": "css", "item_selector": "", "fields": []},
        )


def test_extract_auto_reuses_supplied_rule():
    extraction, detected = extract_auto(
        XPATH_HTML,
        "https://example.com/",
        rule={
            "mode": "css",
            "item_selector": "li.row",
            "fields": [{"name": "名称", "selector": "span.n"}],
        },
    )
    assert extraction.columns == ["名称"]
    assert extraction.rows == [["A"], ["B"]]
    assert detected["mode"] == "css"


def test_extraction_dataclass_defaults():
    extraction = Extraction(columns=["a"], rows=[["1"]])
    assert extraction.warnings == []
