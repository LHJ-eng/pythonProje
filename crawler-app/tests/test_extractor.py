from __future__ import annotations

import pytest

from app.extractor import (
    ExtractionError,
    analyze_page,
    extract_article,
    extract_css,
    extract_table,
    parse_tables,
)
from tests.conftest import SAMPLE_HTML


def test_parse_tables_detects_header_and_rows():
    tables = parse_tables(SAMPLE_HTML)
    assert len(tables) == 1
    assert tables[0].headers == ["名称", "价格", "库存"]
    assert len(tables[0].rows) == 3


def test_extract_table_default_largest():
    extraction = extract_table(parse_tables(SAMPLE_HTML))
    assert extraction.columns == ["名称", "价格", "库存"]
    assert extraction.rows[0] == ["苹果", "5.50", "100"]


def test_extract_table_index_out_of_range():
    with pytest.raises(ExtractionError):
        extract_table(parse_tables(SAMPLE_HTML), table_index=9)


def test_extract_table_without_thead_uses_first_row_header():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"
    extraction = extract_table(
        parse_tables(html), first_row_header=True
    )
    assert extraction.columns == ["a", "b"]
    assert extraction.rows == [["1", "2"]]


def test_extract_css_fields_and_absolute_links():
    extraction = extract_css(
        SAMPLE_HTML,
        "https://shop.example.com/list",
        "div.product",
        [
            {"name": "标题", "selector": "h2", "attr": "text"},
            {"name": "链接", "selector": "a", "attr": "href"},
            {"name": "价格", "selector": ".price", "attr": "text"},
        ],
    )
    assert extraction.columns == ["标题", "链接", "价格"]
    assert extraction.rows == [
        ["商品 A", "https://shop.example.com/p/1", "¥9.9"],
        ["商品 B", "https://shop.example.com/p/2", "¥19.9"],
    ]


def test_extract_css_invalid_selector():
    with pytest.raises(ExtractionError):
        extract_css(SAMPLE_HTML, "https://a.com/", "div[[[", [{"name": "x"}])


def test_extract_article_fallback():
    extraction = extract_article(SAMPLE_HTML, "https://news.example.com/a")
    assert extraction.columns[0] == "标题"
    row = extraction.rows[0]
    assert row[0] == "一篇示例文章"
    assert "用于测试正文抽取功能" in row[-1]


def test_analyze_page_shape():
    data = analyze_page(SAMPLE_HTML, "https://shop.example.com/list")
    assert data["tables"][0]["rows"] == 3
    assert data["tables"][0]["cols"] == 3
    assert data["chars"] > 100
