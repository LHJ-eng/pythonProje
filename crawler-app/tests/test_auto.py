from __future__ import annotations

import pytest

from app.extractor import ExtractionError, analyze_page, extract_auto
from tests.conftest import SAMPLE_HTML


def test_auto_detects_data_table():
    extraction, rule = extract_auto(SAMPLE_HTML, "https://shop.example.com/list")

    assert rule["mode"] == "table"
    assert rule["score"] >= 0.60
    assert extraction.columns == ["名称", "价格", "库存"]
    assert extraction.rows[0] == ["苹果", "5.50", "100"]


def test_auto_infers_product_card_fields():
    html = """
    <main><div class="products">
      <div class="product"><h2>商品 A</h2><span class="price">¥9.9</span><a href="/p/1">查看</a></div>
      <div class="product"><h2>商品 B</h2><span class="price">¥19.9</span><a href="/p/2">查看</a></div>
      <div class="product"><h2>商品 C</h2><span class="price">¥29.9</span><a href="/p/3">查看</a></div>
    </div></main>
    """
    extraction, rule = extract_auto(html, "https://shop.example.com/list")

    assert rule["mode"] == "css"
    assert rule["item_selector"] == "div.products > div.product"
    assert extraction.columns[:2] == ["标题", "价格"]
    assert extraction.rows[0][:2] == ["商品 A", "¥9.9"]
    assert "https://shop.example.com/p/1" in extraction.rows[0]
    assert len(extraction.rows) == 3


def test_auto_handles_list_without_classes_and_reuses_rule():
    first_html = """
    <html><body><ul id="news">
      <li><h3>第一条新闻</h3><p>第一条新闻的摘要内容</p><a href="/1">详情</a></li>
      <li><h3>第二条新闻</h3><p>第二条新闻的摘要内容</p><a href="/2">详情</a></li>
      <li><h3>第三条新闻</h3><p>第三条新闻的摘要内容</p><a href="/3">详情</a></li>
    </ul></body></html>
    """
    first, rule = extract_auto(first_html, "https://news.example.com/")

    assert rule["mode"] == "css"
    assert rule["item_selector"] == "#news > li"
    assert first.rows[0][0] == "第一条新闻"

    second_html = first_html.replace("第一条", "第四条").replace("第二条", "第五条").replace("第三条", "第六条")
    second, reused = extract_auto(second_html, "https://news.example.com/page/2", rule=rule)
    assert reused is rule
    assert second.columns == first.columns
    assert [row[0] for row in second.rows] == ["第四条新闻", "第五条新闻", "第六条新闻"]


def test_auto_ignores_navigation_and_falls_back_to_article():
    paragraph = "这是一段用于验证正文自动识别的完整内容，包含足够的信息和上下文的说明。" * 12
    html = f"""
    <html><head><title>示例报道</title></head><body>
      <nav><ul><li><a href="/a">栏目甲</a></li><li><a href="/b">栏目乙</a></li><li><a href="/c">栏目丙</a></li></ul></nav>
      <main><article><h1>示例报道</h1><p>{paragraph}</p><p>{paragraph}</p></article></main>
    </body></html>
    """
    extraction, rule = extract_auto(html, "https://news.example.com/article")

    assert rule["mode"] == "article"
    assert extraction.columns[0] == "标题"
    assert extraction.rows[0][0] == "示例报道"
    assert "栏目甲" not in extraction.rows[0][-1]


def test_auto_rejects_frameset_with_actionable_message():
    with pytest.raises(ExtractionError, match="框架目录页"):
        extract_auto("<frameset><frame src='left.htm'></frameset>", "https://example.com/")


def test_analyze_page_includes_auto_detection_summary():
    data = analyze_page(SAMPLE_HTML, "https://shop.example.com/list")

    assert data["auto"]["mode"] == "table"
    assert data["auto"]["rows"] == 3
    assert data["auto"]["columns"] == ["名称", "价格", "库存"]
