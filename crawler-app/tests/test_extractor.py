from __future__ import annotations

import pytest

from app.extractor import (
    ExtractionError,
    analyze_page,
    extract_article,
    extract_css,
    extract_json_payloads,
    extract_table,
    extract_auto,
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


MERGED_HEADER_HTML = """
<table>
  <thead>
    <tr><th rowspan="2">姓名</th><th colspan="2">成绩</th></tr>
    <tr><th>数学</th><th>语文</th></tr>
  </thead>
  <tbody>
    <tr><td>张三</td><td>90</td><td>80</td></tr>
    <tr><td>李四</td><td>70</td><td>60</td></tr>
  </tbody>
</table>
"""


def test_table_matrix_merges_multi_row_headers():
    table = parse_tables(MERGED_HEADER_HTML)[0]
    assert table.headers == ["姓名", "成绩 数学", "成绩 语文"]
    assert table.header_rows == 2
    assert table.rows == [["张三", "90", "80"], ["李四", "70", "60"]]


def test_table_matrix_fills_rowspan_in_body():
    html = """
    <table>
      <thead><tr><th>部门</th><th>姓名</th><th>分数</th></tr></thead>
      <tbody>
        <tr><td rowspan="2">研发</td><td>张三</td><td>90</td></tr>
        <tr><td>李四</td><td>85</td></tr>
        <tr><td>市场</td><td>王五</td><td>70</td></tr>
      </tbody>
    </table>
    """
    table = parse_tables(html)[0]
    assert table.headers == ["部门", "姓名", "分数"]
    assert table.rows == [
        ["研发", "张三", "90"],
        ["研发", "李四", "85"],
        ["市场", "王五", "70"],
    ]


def test_extract_css_recovers_when_class_changes():
    html = """
    <div class="item"><h2>商品 A</h2><span class="new-price">10 元</span><a href="/p/1">详情</a></div>
    <div class="item"><h2>商品 B</h2><span class="new-price">20 元</span><a href="/p/2">详情</a></div>
    """
    extraction = extract_css(
        html,
        "https://shop.example.com/list",
        "div.item",
        [
            {"name": "标题", "selector": "h2", "attr": "text"},
            {"name": "价格", "selector": "span.price", "attr": "text"},
            {"name": "链接", "selector": "a.link", "attr": "href"},
        ],
    )
    assert extraction.rows == [
        ["商品 A", "10 元", "https://shop.example.com/p/1"],
        ["商品 B", "20 元", "https://shop.example.com/p/2"],
    ]


def test_extract_css_falls_back_to_unique_link():
    html = """
    <div class="item"><h3>标题一</h3><a href="/detail/1">查看</a></div>
    <div class="item"><h3>标题二</h3><a href="/detail/2">查看</a></div>
    """
    extraction = extract_css(
        html,
        "https://news.example.com/",
        "div.item",
        [
            {"name": "标题", "selector": "h3", "attr": "text"},
            {"name": "链接", "selector": ".missing-link", "attr": "href"},
        ],
    )
    assert extraction.rows == [
        ["标题一", "https://news.example.com/detail/1"],
        ["标题二", "https://news.example.com/detail/2"],
    ]


def test_quality_reports_low_coverage_warning():
    html = """
    <div class="item"><h2>商品 A</h2></div>
    <div class="item"><h2>商品 B</h2></div>
    """
    extraction = extract_css(
        html,
        "https://shop.example.com/list",
        "div.item",
        [
            {"name": "标题", "selector": "h2", "attr": "text"},
            {"name": "价格", "selector": ".missing", "attr": "text"},
        ],
    )
    assert extraction.quality["confidence"] > 0
    assert extraction.quality["field_coverage"]["价格"] == 0.0
    assert extraction.quality["row_completeness"] < 1.0
    assert any("字段命中率偏低" in warning for warning in extraction.warnings)


def test_extract_json_payloads_from_network():
    payload = {
        "code": 0,
        "data": {
            "list": [
                {"name": "A", "price": 10, "url": "/a"},
                {"name": "B", "price": 20, "url": "/b"},
                {"name": "C", "price": 30, "url": "/c"},
            ]
        },
    }
    result = extract_json_payloads([payload], "https://shop.example.com/")
    assert result is not None
    extraction, detected = result
    assert detected["mode"] == "network"
    assert extraction.columns == ["名称", "价格", "链接"]
    assert extraction.rows[0] == ["A", "10", "https://shop.example.com/a"]


def test_extract_auto_prefers_network_payloads():
    payload = {
        "items": [
            {"title": "新闻一", "url": "/n/1"},
            {"title": "新闻二", "url": "/n/2"},
            {"title": "新闻三", "url": "/n/3"},
        ]
    }
    extraction, detected = extract_auto(
        "<html><body><div id='app'></div></body></html>",
        "https://news.example.com/",
        json_payloads=[payload],
    )
    assert detected["mode"] == "network"
    assert len(extraction.rows) == 3
    assert detected["candidates"]["network"] > 0


def test_analyze_page_includes_quality():
    data = analyze_page(SAMPLE_HTML, "https://shop.example.com/list")
    assert data["auto"]["quality"]["confidence"] > 0
    assert data["auto"]["quality"]["rows"] == 3
