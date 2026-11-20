from __future__ import annotations

from app.snapshot import (
    build_snapshot,
    list_candidates,
    page_title,
    sanitize_html,
    table_candidates,
)
from tests.conftest import SAMPLE_HTML

LIST_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><title>列表页</title></head>
<body>
  <div id="hidden-table" style="display:none">
    <table>
      <thead><tr><th>姓名</th><th>分数</th></tr></thead>
      <tbody>
        <tr><td>张三</td><td>90</td></tr>
        <tr><td>李四</td><td>85</td></tr>
      </tbody>
    </table>
  </div>
  <ul class="items">
    <li class="item"><h3>标题一</h3><a href="/a/1">详情</a><span class="price">10元</span><time>2024-01-02</time></li>
    <li class="item"><h3>标题二</h3><a href="/a/2">详情</a><span class="price">20元</span><time>2024-02-03</time></li>
    <li class="item"><h3>标题三</h3><a href="/a/3">详情</a><span class="price">30元</span><time>2024-03-04</time></li>
  </ul>
</body>
</html>
"""


def test_sanitize_removes_dangerous_content_and_injects_base():
    html = """<html><head>
      <title>危险页面</title>
      <script>alert(1)</script>
      <meta http-equiv="refresh" content="0;url=/next">
      <link rel="stylesheet" href="/style.css">
    </head><body onload="boot()">
      <a href="javascript:alert(1)" onclick="steal()">跳转</a>
      <img src="data:text/html;base64,PHNjcmlwdD4=" alt="x">
      <div id="secret" style="display:none">隐藏数据</div>
    </body></html>"""
    snapshot = sanitize_html(html, "https://example.com/base/")

    assert "<script" not in snapshot
    assert "onload=" not in snapshot
    assert "onclick=" not in snapshot
    assert 'http-equiv="refresh"' not in snapshot
    assert 'rel="stylesheet"' not in snapshot
    assert "javascript:" not in snapshot
    assert "data:text/html" not in snapshot
    assert 'href="#"' in snapshot
    assert '<base href="https://example.com/base/"' in snapshot
    assert "display: revert" in snapshot
    assert "隐藏数据" in snapshot
    assert snapshot.lower().count("<!doctype") == 1


def test_table_candidates_include_hidden_tables_and_rule():
    candidates = table_candidates(LIST_HTML)
    assert candidates
    table = candidates[0]
    assert table["hidden"] is True
    assert table["headers"] == ["姓名", "分数"]
    assert table["rows"] == 2
    assert table["cols"] == 2
    assert table["sample"][0] == ["张三", "90"]
    assert table["item_selector"].endswith("tr")
    assert table["rule"]["mode"] == "css"
    assert table["rule"]["fields"][0]["selector"] == "td:nth-child(1)"
    assert table["rule"]["fields"][1]["name"] == "分数"


def test_list_candidates_generate_deduped_rule():
    candidates = list_candidates(LIST_HTML, "https://example.com/")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["count"] == 3
    assert "li" in candidate["item_selector"]
    names = {field["name"] for field in candidate["fields"]}
    assert {"标题", "链接"} <= names
    assert all(field["selector_type"] == "css" for field in candidate["fields"])
    assert len(candidate["sample"]) == 3
    assert candidate["sample"][0][0] == "标题一"
    assert candidate["rule"]["item_selector"] == candidate["item_selector"]


def test_build_snapshot_returns_title_and_candidates():
    data = build_snapshot(SAMPLE_HTML, "https://example.com/list/")
    assert data["title"] == "示例商品列表"
    assert page_title(SAMPLE_HTML) == "示例商品列表"
    assert data["tables"][0]["headers"] == ["名称", "价格", "库存"]
    assert data["tables"][0]["rows"] == 3
    assert data["snapshot_html"].startswith("<!DOCTYPE html>")
    assert '<base href="https://example.com/list/"' in data["snapshot_html"]
    assert data["source_chars"] > 0
    assert data["snapshot_chars"] > 0


MERGED_TABLE_HTML = """
<html><body>
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
</body></html>
"""


def test_table_candidates_handle_merged_headers():
    candidates = table_candidates(MERGED_TABLE_HTML)
    assert candidates
    table = candidates[0]
    assert table["headers"] == ["姓名", "成绩 数学", "成绩 语文"]
    assert table["rows"] == 2
    assert table["cols"] == 3
    assert table["sample"][0] == ["张三", "90", "80"]
    assert "tbody" in table["item_selector"]
    assert table["rule"]["fields"][1]["selector"] == "td:nth-child(2)"
