"""页面解析：自动表格、CSS 选择器、正文抽取三种模式。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .security import clean_text


class ExtractionError(ValueError):
    """选择器错误、未找到表格/条目等。"""


@dataclass
class TableData:
    index: int
    headers: list[str]
    rows: list[list[str]]
    has_thead: bool


@dataclass
class Extraction:
    columns: list[str]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _collapse(value: str) -> str:
    return re.sub(r"[\s\u00a0]+", " ", value or "").strip()


def _unique_columns(names: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for i, raw in enumerate(names):
        name = _collapse(raw) or f"列{i + 1}"
        name = name[:200]
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        result.append(name)
    return result


def _cell_value(cell) -> str:
    for br in cell.find_all("br"):
        br.replace_with(" ")
    return _collapse(cell.get_text(" ", strip=True))


def _row_cells(tr) -> list[tuple[str, int]]:
    cells: list[tuple[str, int]] = []
    for cell in tr.find_all(["td", "th"], recursive=False):
        try:
            colspan = min(int(cell.get("colspan", 1)), 50)
        except (TypeError, ValueError):
            colspan = 1
        cells.append((_cell_value(cell), max(colspan, 1)))
    return cells


def parse_tables(html: str) -> list[TableData]:
    soup = make_soup(html)
    result: list[TableData] = []
    for index, table in enumerate(soup.find_all("table")):
        if table.find_parent("table") is not None:
            continue  # 跳过嵌套表格，避免重复
        thead = table.find("thead")
        header_row = None
        if thead:
            tr = thead.find("tr")
            if tr:
                header_row = [value for value, span in _row_cells(tr) for _ in range(span)]

        body_rows = []
        for tr in table.find_all("tr"):
            if thead and tr.find_parent("thead") is not None:
                continue
            cells = _row_cells(tr)
            if cells:
                body_rows.append([value for value, span in cells for _ in range(span)])

        if header_row is None and body_rows:
            first_tr = table.find("tr")
            if first_tr and first_tr.find("th") and first_tr.find_parent("thead") is None:
                header_row = body_rows.pop(0)
                if not any(header_row):
                    header_row = None
        if not body_rows:
            continue
        width = max(len(row) for row in [header_row or []] + body_rows)
        if width == 0:
            continue
        headers = _unique_columns(
            list(header_row or []) + [""] * max(0, width - len(header_row or []))
        ) if header_row else [f"列{i + 1}" for i in range(width)]
        normalized = [row + [""] * (width - len(row)) for row in body_rows]
        result.append(
            TableData(
                index=len(result),
                headers=headers,
                rows=normalized,
                has_thead=header_row is not None,
            )
        )
    return result


def extract_table(
    tables: list[TableData],
    *,
    table_index: int | None = None,
    first_row_header: bool = False,
) -> Extraction:
    if not tables:
        raise ExtractionError("页面中没有检测到 HTML 表格，可改用 CSS 选择器模式")
    if table_index is None:
        # 默认选数据量最大的表格
        chosen = max(tables, key=lambda t: len(t.rows) * max(len(t.headers), 1))
    else:
        if table_index < 0 or table_index >= len(tables):
            raise ExtractionError(
                f"表格序号超出范围：页面共检测到 {len(tables)} 个表格"
            )
        chosen = tables[table_index]

    headers = chosen.headers
    rows = chosen.rows
    if first_row_header and not chosen.has_thead and rows:
        headers = _unique_columns(rows[0])
        rows = rows[1:]
    return Extraction(columns=_unique_columns(headers), rows=rows)


def _matches(tag, selector: str) -> bool:
    try:
        import soupsieve

        return soupsieve.match(selector, tag)
    except Exception:
        return False


def extract_css(
    html: str,
    base_url: str,
    item_selector: str,
    fields: list[dict],
) -> Extraction:
    item_selector = (item_selector or "").strip()
    if not item_selector:
        raise ExtractionError("请填写条目选择器（例如 div.product）")
    if not fields:
        raise ExtractionError("至少需要一个字段映射")
    soup = make_soup(html)
    try:
        items = soup.select(item_selector)
    except Exception as exc:
        raise ExtractionError(f"条目选择器语法错误：{exc}") from exc
    if not items:
        raise ExtractionError(
            f"未匹配到任何条目（选择器：{item_selector}）。"
            "可先点「分析页面」查看页面结构，或检查是否为 JS 动态渲染。"
        )

    columns = _unique_columns([f.get("name") or f"字段{i + 1}" for i, f in enumerate(fields)])
    rows: list[list[str]] = []
    warnings: list[str] = []
    for item in items:
        row: list[str] = []
        for spec in fields:
            selector = (spec.get("selector") or "").strip()
            attr = (spec.get("attr") or "text").strip().lower()
            value = ""
            try:
                if not selector:
                    node = item
                elif selector.startswith("@"):
                    value = item.get(selector[1:], "") or ""
                    node = None
                else:
                    node = item.select_one(selector)
                    if node is None and _matches(item, selector):
                        node = item
                if node is not None and not value:
                    if attr == "text":
                        value = _collapse(node.get_text(" ", strip=True))
                    elif attr == "html":
                        value = str(node)
                    else:
                        value = node.get(attr, "") or ""
                        if attr in {"href", "src", "poster"} and value:
                            value = urljoin(base_url, value)
            except Exception as exc:
                warnings.append(f"字段 {spec.get('name')} 解析失败：{exc}")
            row.append(_collapse(value))
        if any(row):
            rows.append(row)
    if not rows:
        raise ExtractionError("匹配到条目，但所有字段都是空的，请检查字段选择器")
    return Extraction(columns=columns, rows=rows, warnings=warnings[:10])


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return _collapse(tag["content"])
    return ""


def _fallback_article(soup: BeautifulSoup, url: str) -> tuple[list[str], list[list[str]]]:
    for tag in soup(
        ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg"]
    ):
        tag.decompose()

    candidates = []
    for selector in [
        "article",
        "main",
        "[role=main]",
        ".article-content",
        ".entry-content",
        ".post-content",
        ".article",
        ".content",
        "#content",
    ]:
        candidates.extend(soup.select(selector))
    if not candidates:
        candidates = [soup.body or soup]

    def text_size(node) -> int:
        return sum(len(p.get_text(" ", strip=True)) for p in node.find_all("p"))

    best = max(candidates, key=text_size)
    blocks = []
    for node in best.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "pre"]):
        text = _collapse(node.get_text(" ", strip=True))
        if len(text) >= 2:
            blocks.append(text)
    body = "\n".join(blocks)
    if len(body) < 120:
        body = re.sub(r"\n{3,}", "\n\n", best.get_text("\n", strip=True))

    title = _meta(soup, "og:title", "twitter:title")
    if not title:
        h1 = soup.find("h1")
        title = _collapse(h1.get_text(" ", strip=True)) if h1 else ""
    if not title and soup.title:
        title = _collapse(soup.title.get_text(" ", strip=True))
    author = _meta(soup, "author", "article:author")
    date = _meta(soup, "article:published_time", "date", "datePublished", "pubdate")
    if not date:
        time_tag = soup.find("time")
        if time_tag:
            date = _collapse(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
    summary = _meta(soup, "description", "og:description")
    return ["标题", "作者", "日期", "摘要", "来源URL", "正文"], [
        [title, author, date, summary, url, body[:200_000]]
    ]


def extract_article(html: str, url: str) -> Extraction:
    soup = make_soup(html)

    try:  # 可选依赖：装了 trafilatura 时优先使用，正文质量更好
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        if text and len(text.strip()) >= 80:
            meta = trafilatura.extract_metadata(html, default_url=url)
            title = (getattr(meta, "title", "") or "") if meta else ""
            if not title:
                title = _meta(soup, "og:title") or (
                    _collapse(soup.title.get_text(" ", strip=True)) if soup.title else ""
                )
            author = (getattr(meta, "author", "") or "") if meta else ""
            date = (getattr(meta, "date", "") or "") if meta else ""
            summary = (getattr(meta, "description", "") or "") if meta else ""
            return Extraction(
                columns=["标题", "作者", "日期", "摘要", "来源URL", "正文"],
                rows=[[title, author, date, summary, url, text[:200_000]]],
            )
    except Exception:
        pass

    columns, rows = _fallback_article(soup, url)
    if not rows[0][-1].strip():
        raise ExtractionError("未能提取到正文内容，请尝试浏览器渲染或改用 CSS 选择器模式")
    return Extraction(columns=columns, rows=rows)


def analyze_page(html: str, url: str) -> dict:
    """返回页面结构摘要，供前端选择表格 / 预览正文。"""
    soup = make_soup(html)
    tables = parse_tables(html)
    try:
        article = extract_article(html, url)
        article_text = article.rows[0][-1]
        article_preview = article_text[:600]
        article_len = len(article_text)
    except ExtractionError:
        article_preview = ""
        article_len = 0

    title = _meta(soup, "og:title") or ""
    if not title:
        h1 = soup.find("h1")
        title = _collapse(h1.get_text(" ", strip=True)) if h1 else ""
    if not title and soup.title:
        title = _collapse(soup.title.get_text(" ", strip=True))

    return {
        "title": title,
        "url": url,
        "tables": [
            {
                "index": t.index,
                "rows": len(t.rows),
                "cols": len(t.headers),
                "headers": t.headers[:30],
                "preview": t.rows[:5],
            }
            for t in tables
        ],
        "article": {
            "length": article_len,
            "preview": article_preview,
        },
        "links": len(soup.find_all("a")),
        "chars": len(html),
    }
