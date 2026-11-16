from __future__ import annotations

import pytest

from app.extractor import (
    ExtractionError,
    _dedupe_repeated,
    analyze_page,
    extract_auto,
    extract_feed,
    extract_structured,
    frame_sources,
)
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


def test_auto_deduplicates_nested_link_text():
    html = """
    <html><body><ul class="news">
      <li><a href="/1"><p>新闻标题一</p><span>2026-01-01</span></a></li>
      <li><a href="/2"><p>新闻标题二</p><span>2026-01-02</span></a></li>
      <li><a href="/3"><p>新闻标题三</p><span>2026-01-03</span></a></li>
    </ul></body></html>
    """
    extraction, rule = extract_auto(html, "https://news.example.com/")

    assert rule["mode"] == "css"
    assert extraction.columns.count("标题") == 1
    assert "日期" in extraction.columns
    assert "链接" in extraction.columns
    title_index = extraction.columns.index("标题")
    assert extraction.rows[0][title_index] == "新闻标题一"
    # 不应出现「标题 标题 日期」这类重复拼接字段
    assert not any(
        value.count("新闻标题一") > 1 for row in extraction.rows for value in row
    )


def test_auto_extracts_jsonld_item_list():
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"ItemList","itemListElement":[
      {"@type":"ListItem","position":1,"url":"/p/1","name":"商品 A",
       "item":{"@type":"Product","name":"商品 A","offers":{"@type":"Offer","price":"9.9"}}},
      {"@type":"ListItem","position":2,"url":"/p/2","name":"商品 B",
       "item":{"@type":"Product","name":"商品 B","offers":{"@type":"Offer","price":"19.9"}}},
      {"@type":"ListItem","position":3,"url":"/p/3","name":"商品 C",
       "item":{"@type":"Product","name":"商品 C","offers":{"@type":"Offer","price":"29.9"}}}
    ]}</script></head><body><div id="app"></div></body></html>
    """
    extraction, rule = extract_auto(html, "https://shop.example.com/")

    assert rule["mode"] == "structured"
    assert len(extraction.rows) == 3
    assert "名称" in extraction.columns
    assert "价格" in extraction.columns
    assert extraction.rows[0][extraction.columns.index("名称")] == "商品 A"
    assert extraction.rows[0][extraction.columns.index("链接")] == "https://shop.example.com/p/1"


def test_auto_extracts_embedded_next_data():
    html = """
    <html><body><div id="app"></div>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"items":[
      {"title":"甲","price":1,"url":"/a"},
      {"title":"乙","price":2,"url":"/b"},
      {"title":"丙","price":3,"url":"/c"}
    ]}}}</script></body></html>
    """
    extraction, rule = extract_auto(html, "https://shop.example.com/")

    assert rule["mode"] == "structured"
    assert [row[0] for row in extraction.rows] == ["甲", "乙", "丙"]


def test_structured_returns_none_without_records():
    assert extract_structured("<html><body><p>普通页面</p></body></html>", "https://a.com") is None


def test_extract_feed_supports_rss_and_atom():
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item><title>第一条</title><link>/1</link><pubDate>2026-01-01</pubDate>
        <description>摘要一</description></item>
      <item><title>第二条</title><link>/2</link><pubDate>2026-01-02</pubDate>
        <description>摘要二</description></item>
    </channel></rss>"""
    extraction, rule = extract_feed(rss, "https://news.example.com/")

    assert rule["mode"] == "feed"
    assert extraction.columns == ["标题", "链接", "日期", "摘要", "作者"]
    assert extraction.rows[0][0:2] == ["第一条", "https://news.example.com/1"]
    assert len(extraction.rows) == 2

    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>原子条目</title><link href="/a"/><updated>2026-02-01</updated>
        <summary>摘要</summary><author><name>作者甲</name></author></entry>
    </feed>"""
    atom_extraction, _ = extract_feed(atom, "https://news.example.com/")
    assert atom_extraction.rows[0][0] == "原子条目"
    assert atom_extraction.rows[0][1] == "https://news.example.com/a"
    assert atom_extraction.rows[0][4] == "作者甲"


def test_frame_sources_resolves_absolute_urls():
    html = "<html><frameset><frame name='main' src='content.html'><frame src='/left.htm'></frameset></html>"
    assert frame_sources(html, "https://example.com/dir/index.htm") == [
        ("main", "https://example.com/dir/content.html"),
        ("", "https://example.com/left.htm"),
    ]


def test_dedupe_repeated_collapses_responsive_duplicates():
    assert _dedupe_repeated("新闻标题 新闻标题 新闻标题") == "新闻标题"
    assert _dedupe_repeated("正常文本 没有重复") == "正常文本 没有重复"
