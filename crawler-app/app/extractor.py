"""页面解析：自动表格、CSS / XPath 选择器、正文抽取三种模式。"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .security import clean_text


class ExtractionError(ValueError):
    """选择器错误、未找到表格/条目等。"""


def _quality(columns: list[str], rows: list[list[str]]) -> dict:
    """计算提取质量与置信度，帮助用户判断是否需要调整规则。"""
    row_count = len(rows)
    col_count = len(columns)
    if not row_count or not col_count:
        return {
            "rows": row_count,
            "columns": col_count,
            "field_coverage": {},
            "average_field_coverage": 0.0,
            "row_completeness": 0.0,
            "confidence": 0.0,
            "empty_cells": 0,
        }
    field_coverage: dict[str, float] = {}
    nonempty = 0
    for index, column in enumerate(columns):
        hit = sum(
            1 for row in rows
            if index < len(row) and str(row[index]).strip()
        )
        field_coverage[column] = round(hit / row_count, 3)
        nonempty += hit
    total = row_count * col_count
    coverage = nonempty / total
    row_completeness = sum(
        sum(1 for cell in row if str(cell).strip()) / max(len(row), 1)
        for row in rows
    ) / row_count
    average_field = sum(field_coverage.values()) / col_count
    confidence = (
        0.45 * coverage
        + 0.25 * row_completeness
        + 0.15 * min(row_count / 5, 1)
        + 0.15 * min(col_count / 3, 1)
    )
    return {
        "rows": row_count,
        "columns": col_count,
        "field_coverage": field_coverage,
        "average_field_coverage": round(average_field, 3),
        "row_completeness": round(row_completeness, 3),
        "confidence": round(min(confidence, 1.0), 3),
        "empty_cells": total - nonempty,
    }


@dataclass
class TableData:
    index: int
    headers: list[str]
    rows: list[list[str]]
    has_thead: bool
    header_rows: int = 0


@dataclass
class Extraction:
    columns: list[str]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)
    quality: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.quality:
            self.quality = _quality(self.columns, self.rows)


def _low_coverage_warning(extraction: Extraction) -> None:
    """字段命中率过低时提示用户，避免拿到一堆空列还以为抓取成功。"""
    coverage = extraction.quality.get("field_coverage") or {}
    low = [name for name, ratio in coverage.items() if ratio < 0.5]
    if not low:
        return
    extraction.warnings = (
        extraction.warnings
        + [f"字段命中率偏低：{'、'.join(low[:5])}，可检查选择器或开启浏览器渲染"]
    )[:12]


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _collapse(value: str) -> str:
    return re.sub(r"[\s\u00a0]+", " ", value or "").strip()


def _dedupe_repeated(value: str) -> str:
    """折叠“标题 标题 标题”这类因响应式/隐藏节点造成的重复文本。"""
    tokens = value.split()
    for repeat in (4, 3, 2):
        if len(tokens) >= repeat and len(tokens) % repeat == 0:
            size = len(tokens) // repeat
            if tokens[:size] * repeat == tokens:
                return " ".join(tokens[:size])
    return value


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


def _span(cell, name: str) -> int:
    try:
        return max(1, min(int(cell.get(name, 1)), 50))
    except (TypeError, ValueError):
        return 1


def table_matrix(table) -> tuple[list[str], list[list[str]], int, str, bool]:
    """把表格还原为二维网格，正确处理 rowspan / colspan 与多行表头。

    返回 (表头, 数据行, 表头行数, 数据单元格标签, 是否检测到表头)。
    """
    rows_nodes = [
        tr for tr in table.find_all("tr")
        if tr.find_parent("table") is table
    ]
    grid: list[list[str]] = []
    pending: dict[int, list] = {}
    for tr in rows_nodes:
        row: list[str] = []
        col = 0

        def fill_pending() -> None:
            nonlocal col
            while col in pending:
                value, remaining = pending[col]
                row.append(value)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = [value, remaining - 1]
                col += 1

        fill_pending()
        for cell in tr.find_all(["td", "th"], recursive=False):
            fill_pending()
            value = _cell_value(cell)
            colspan = _span(cell, "colspan")
            rowspan = _span(cell, "rowspan")
            for offset in range(colspan):
                row.append(value)
                if rowspan > 1:
                    pending[col + offset] = [value, rowspan - 1]
            col += colspan
        # 补齐行尾仍然生效的 rowspan 单元格（不删除更靠前、属于下一行的挂起单元格）
        col = len(row)
        while True:
            future = [position for position in pending if position >= col]
            if not future:
                break
            next_col = min(future)
            row.extend([""] * (next_col - col))
            col = next_col
            fill_pending()
            col = len(row)
        grid.append(row)

    if not grid:
        return [], [], 0, "td", False
    width = max(len(row) for row in grid)
    if width == 0:
        return [], [], 0, "td", False
    for row in grid:
        row.extend([""] * (width - len(row)))

    thead_rows = [
        tr for tr in rows_nodes
        if tr.find_parent("thead") is not None
    ]
    header_count = len(thead_rows)
    source = "thead" if header_count else "none"
    if not header_count and rows_nodes:
        first_cells = rows_nodes[0].find_all(["td", "th"], recursive=False)
        if first_cells:
            th_ratio = sum(1 for cell in first_cells if cell.name == "th") / len(first_cells)
            if th_ratio >= 0.6:
                header_count = 1
                source = "th"
                if len(rows_nodes) > 1:
                    second_cells = rows_nodes[1].find_all(
                        ["td", "th"], recursive=False
                    )
                    if second_cells and (
                        sum(1 for cell in second_cells if cell.name == "th")
                        / len(second_cells)
                        >= 0.6
                    ):
                        header_count = 2
    header_count = max(0, min(header_count, len(grid)))

    if header_count:
        raw_headers: list[str] = []
        for column in range(width):
            values: list[str] = []
            for row_index in range(header_count):
                value = grid[row_index][column]
                if value and (not values or values[-1] != value):
                    values.append(value)
            raw_headers.append(" ".join(values))
        headers = _unique_columns(raw_headers)
    else:
        headers = [f"列{index + 1}" for index in range(width)]

    body = [row for row in grid[header_count:] if any(cell.strip() for cell in row)]
    first_body_cells = []
    if header_count < len(rows_nodes):
        first_body_cells = rows_nodes[header_count].find_all(
            ["td", "th"], recursive=False
        )
    cell_tag = (
        "td"
        if not first_body_cells or any(cell.name == "td" for cell in first_body_cells)
        else "th"
    )
    return headers, body, header_count, cell_tag, header_count > 0


def parse_tables(html: str) -> list[TableData]:
    soup = make_soup(html)
    result: list[TableData] = []
    for table in soup.find_all("table"):
        if table.find_parent("table") is not None:
            continue  # 跳过嵌套表格，避免重复
        headers, body, header_rows, _, has_thead = table_matrix(table)
        if not body or not headers:
            continue
        result.append(
            TableData(
                index=len(result),
                headers=headers,
                rows=body,
                has_thead=has_thead,
                header_rows=header_rows,
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
    *,
    item_selector_type: str = "css",
) -> Extraction:
    item_selector = (item_selector or "").strip()
    if not item_selector:
        raise ExtractionError("请填写条目选择器（例如 div.product）")
    if not fields:
        raise ExtractionError("至少需要一个字段映射")
    selector_kind = (item_selector_type or "css").strip().lower()
    if selector_kind == "xpath" or any(
        (spec.get("selector_type") or "css").strip().lower() == "xpath"
        for spec in fields
    ):
        return _extract_xpath(
            html,
            base_url,
            item_selector,
            fields,
            item_selector_type=selector_kind,
        )
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
            try:
                value = _css_field_value(item, selector, attr, base_url)
            except Exception as exc:
                warnings.append(f"字段 {spec.get('name')} 解析失败：{exc}")
                value = ""
            row.append(_dedupe_repeated(_collapse(value)))
        if any(row):
            rows.append(row)
    if not rows:
        raise ExtractionError("匹配到条目，但所有字段都是空的，请检查字段选择器")
    extraction = Extraction(columns=columns, rows=rows, warnings=warnings[:10])
    _low_coverage_warning(extraction)
    return extraction


_CLASS_PART = re.compile(r"\.[-_a-zA-Z][-_a-zA-Z0-9]*")


def _relax_selector(selector: str) -> str:
    """去掉选择器里的 class，用于字段选择器失效时的保守回退。"""
    relaxed = _CLASS_PART.sub("", selector or "")
    relaxed = re.sub(r"\s+", " ", relaxed).strip()
    return relaxed.strip(" >+~")


def _css_field_value(
    item, selector: str, attr: str, base_url: str, *, relax: bool = True
) -> str:
    """按 CSS 选择器从条目中取值（支持 @属性、text、html 与常用链接属性）。

    字段为空时做保守自愈：去掉 class 后在条目内唯一命中才采用；
    链接 / 图片字段在条目内恰有一个带该属性的节点时回退到该节点，
    避免站点改版把 class 换掉后整列变成空值。
    """
    value = ""
    node = None
    if not selector:
        node = item
    elif selector.startswith("@"):
        getter = getattr(item, "get", None)
        value = (getter(selector[1:], "") if getter else "") or ""
    else:
        node = item.select_one(selector)
        if node is None and item is not None and _matches(item, selector):
            node = item
        if node is None and relax:
            relaxed = _relax_selector(selector)
            if relaxed and relaxed != selector:
                try:
                    candidates = item.select(relaxed)
                except Exception:
                    candidates = []
                if len(candidates) == 1:
                    node = candidates[0]
    if node is not None and not value:
        if attr == "text":
            value = _collapse(node.get_text(" ", strip=True))
        elif attr == "html":
            value = str(node)
        else:
            value = node.get(attr, "") or ""
            if attr in {"href", "src", "poster"} and value:
                value = urljoin(base_url, value)
    if not value and relax and attr in {"href", "src"}:
        tag_name = "a" if attr == "href" else "img"
        try:
            candidates = [
                node
                for node in item.select(f"{tag_name}[{attr}]")
                if str(node.get(attr) or "").strip()
            ]
        except Exception:
            candidates = []
        if len(candidates) == 1:
            value = urljoin(base_url, str(candidates[0].get(attr) or ""))
    return str(value or "")


def _to_lxml(node):
    try:
        import lxml.html

        return lxml.html.fromstring(str(node))
    except Exception:
        return None


def _to_soup(node) -> BeautifulSoup:
    try:
        import lxml.html

        return make_soup(
            lxml.html.tostring(node, encoding="unicode", method="html")
        )
    except Exception:
        return make_soup("")


def _xpath_nodes(root, expression: str) -> list:
    try:
        return root.xpath(expression)
    except Exception as exc:
        raise ExtractionError(f"XPath 表达式语法错误：{exc}") from exc


def _xpath_text(node) -> str:
    try:
        return _collapse(" ".join(str(part) for part in node.itertext()))
    except Exception:
        return ""


def _xpath_value(nodes: list, attr: str, base_url: str) -> str:
    node = nodes[0] if nodes else None
    if node is None:
        return ""
    if isinstance(node, str):
        return _collapse(node)
    if attr == "text":
        return _xpath_text(node)
    if attr == "html":
        try:
            import lxml.html

            return lxml.html.tostring(node, encoding="unicode", method="html")
        except Exception:
            return ""
    value = node.get(attr, "") or ""
    if attr in {"href", "src", "poster"} and value:
        value = urljoin(base_url, value)
    return str(value or "")


def _extract_xpath(
    html: str,
    base_url: str,
    item_selector: str,
    fields: list[dict],
    *,
    item_selector_type: str = "xpath",
) -> Extraction:
    """XPath 模式：条目与字段都可使用 XPath，字段仍可回退到 CSS。"""
    using_css_items = (item_selector_type or "xpath").strip().lower() == "css"
    warnings: list[str] = []
    if using_css_items:
        soup = make_soup(html)
        try:
            items = list(soup.select(item_selector))
        except Exception as exc:
            raise ExtractionError(f"条目选择器语法错误：{exc}") from exc
    else:
        try:
            import lxml.html

            root = lxml.html.document_fromstring(html)
        except Exception as exc:
            raise ExtractionError(f"HTML 解析失败：{exc}") from exc
        items = [node for node in _xpath_nodes(root, item_selector) if hasattr(node, "itertext")]
    if not items:
        raise ExtractionError(
            f"未匹配到任何条目（选择器：{item_selector}）。"
            "可先点「分析页面」查看页面结构，或检查是否为 JS 动态渲染。"
        )

    columns = _unique_columns([f.get("name") or f"字段{i + 1}" for i, f in enumerate(fields)])
    rows: list[list[str]] = []
    for item in items:
        row: list[str] = []
        css_item = item if using_css_items else None
        for spec in fields:
            selector = (spec.get("selector") or "").strip()
            attr = (spec.get("attr") or "text").strip().lower()
            default_kind = "css" if using_css_items else "xpath"
            kind = (spec.get("selector_type") or default_kind).strip().lower()
            value = ""
            try:
                if kind == "xpath":
                    element = item if not using_css_items else _to_lxml(item)
                    if element is not None:
                        nodes = (
                            _xpath_nodes(element, selector) if selector else [element]
                        )
                        value = _xpath_value(nodes, attr, base_url)
                else:
                    if css_item is None:
                        css_item = _to_soup(item)
                    value = _css_field_value(css_item, selector, attr, base_url)
            except Exception as exc:
                warnings.append(f"字段 {spec.get('name')} 解析失败：{exc}")
                value = ""
            row.append(_dedupe_repeated(_collapse(value)))
        if any(row):
            rows.append(row)
    if not rows:
        raise ExtractionError("匹配到条目，但所有字段都是空的，请检查字段选择器")
    extraction = Extraction(columns=columns, rows=rows, warnings=warnings[:10])
    _low_coverage_warning(extraction)
    return extraction


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


def _readability_extract(html: str, url: str) -> tuple[str, str] | None:
    """用 readability-lxml（Mozilla Readability 的 Python 移植）抽取主内容正文与标题。

    返回 (title, body_text)，失败返回 None。readability 擅长剥离导航、侧栏、广告，
    保留真正的正文容器。
    """
    try:
        from readability import Document
    except ImportError:
        return None
    try:
        doc = Document(html, url=url)
        title = _collapse(doc.title() or "")
        summary_html = doc.summary() or ""
        if not summary_html:
            return None
        soup = make_soup(summary_html)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # 优先用正文里的第一个标题标签（h1/h2）作为文章标题，避免取到站点 <title>
        heading = soup.find(["h1", "h2"])
        if heading:
            heading_title = _collapse(heading.get_text(" ", strip=True))
            if heading_title:
                title = heading_title
                heading.decompose()
        text = _collapse(soup.get_text("\n", strip=True))
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text.strip()) < 80:
            return None
        return title, text[:200_000]
    except Exception:
        return None


def _main_content_html(html: str, url: str = "") -> str:
    """返回 readability 清洗后的主内容 HTML（剥离 nav/aside/广告）。

    用于在主内容容器范围内重新做列表识别，避免页面导航/推荐位干扰。
    """
    try:
        from readability import Document
    except ImportError:
        return html
    try:
        summary = Document(html, url=url).summary() or ""
        return summary if summary.strip() else html
    except Exception:
        return html


def _article_quality_score(text: str) -> float:
    """正文质量打分：越长越好，但短句/链接行过多会扣分。"""
    if not text:
        return 0.0
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    link_lines = sum(
        1 for line in lines if line.startswith(("http://", "https://", "www."))
    )
    short_lines = sum(1 for line in lines if len(line) < 8)
    density_bonus = 1.0 - min(0.6, link_lines / len(lines))
    short_penalty = 1.0 - min(0.5, short_lines / max(len(lines), 1))
    return len(text) * density_bonus * short_penalty


def _build_article_extraction(
    title: str, author: str, date: str, summary: str, url: str, body: str
) -> Extraction:
    return Extraction(
        columns=["标题", "作者", "日期", "摘要", "来源URL", "正文"],
        rows=[[title, author, date, summary, url, body[:200_000]]],
    )


def extract_article(html: str, url: str, *, browser_rendered: bool = False) -> Extraction:
    soup = make_soup(html)
    candidates: list[tuple[float, Extraction]] = []

    # 候选 1：trafilatura
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=not browser_rendered,
            deduplicate=True,
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
            extraction = _build_article_extraction(title, author, date, summary, url, text)
            candidates.append((_article_quality_score(text), extraction))
    except Exception:
        pass

    # 候选 2：readability-lxml（剥离导航/侧栏后取正文）
    readability_result = _readability_extract(html, url)
    if readability_result:
        title, body = readability_result
        if not title:
            title = _meta(soup, "og:title") or (
                _collapse(soup.title.get_text(" ", strip=True)) if soup.title else ""
            )
        extraction = _build_article_extraction(title, "", "", "", url, body)
        candidates.append((_article_quality_score(body), extraction))

    if candidates:
        return max(candidates, key=lambda item: item[0])[1]

    columns, rows = _fallback_article(soup, url)
    if not rows[0][-1].strip():
        raise ExtractionError("未能提取到正文内容，请尝试浏览器渲染或改用 CSS 选择器模式")
    return Extraction(columns=columns, rows=rows)


_AUTO_BLOCKED_ANCESTORS = {"nav", "header", "footer", "aside", "form"}
_AUTO_TEXT_TAGS = {"p", "span", "strong", "em", "small", "time", "div"}
_AUTO_LEAF_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "a",
    "strong", "em", "small", "time", "img", "div",
}


def _safe_css_ident(value: str) -> bool:
    return bool(re.fullmatch(r"-?[_a-zA-Z]+[_a-zA-Z0-9-]*", value or ""))


def _auto_hidden(tag) -> bool:
    if tag.has_attr("hidden") or str(tag.get("aria-hidden", "")).lower() == "true":
        return True
    style = str(tag.get("style", "")).replace(" ", "").lower()
    return "display:none" in style or "visibility:hidden" in style


def _auto_blocked(tag) -> bool:
    if _auto_hidden(tag):
        return True
    return any(
        getattr(parent, "name", "") in _AUTO_BLOCKED_ANCESTORS
        for parent in tag.parents
    )


def _structure_signature(item) -> set[str]:
    paths: set[str] = set()
    visited = 0

    def walk(node, prefix: str, depth: int) -> None:
        nonlocal visited
        if depth > 3 or visited >= 100:
            return
        for child in node.find_all(recursive=False):
            if _auto_hidden(child):
                continue
            visited += 1
            path = f"{prefix}>{child.name}" if prefix else child.name
            paths.add(path)
            walk(child, path, depth + 1)

    walk(item, "", 0)
    return paths


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _nth_of_type(tag) -> str:
    siblings = [node for node in tag.parent.find_all(tag.name, recursive=False)]
    return f"{tag.name}:nth-of-type({siblings.index(tag) + 1})"


def _auto_parent_selector(parent, soup) -> str:
    if getattr(parent, "name", None) in {"body", "[document]", None}:
        return "body"
    parent_id = str(parent.get("id", ""))
    if _safe_css_ident(parent_id) and len(soup.select(f"#{parent_id}")) == 1:
        return f"#{parent_id}"
    classes = [str(value) for value in parent.get("class", [])]
    safe_classes = [value for value in classes if _safe_css_ident(value)]
    if safe_classes:
        return f"{parent.name}.{safe_classes[0]}"

    segments: list[str] = []
    current = parent
    while getattr(current, "name", None) not in {"body", "[document]", None}:
        current_id = str(current.get("id", ""))
        if _safe_css_ident(current_id):
            segments.append(f"#{current_id}")
            break
        segments.append(_nth_of_type(current))
        current = current.parent
    else:
        segments.append("body")
    return " > ".join(reversed(segments))


def _auto_relative_selector(item, node) -> str:
    classes = [str(value) for value in node.get("class", [])]
    safe_classes = [value for value in classes if _safe_css_ident(value)]
    if safe_classes:
        return f"{node.name}.{safe_classes[0]}"
    segments: list[str] = []
    current = node
    while current is not item and getattr(current, "name", None) not in {None, "[document]"}:
        segments.append(_nth_of_type(current))
        current = current.parent
    return " > ".join(reversed(segments))


def _auto_field_name(node, attr: str) -> str:
    semantic = " ".join(
        [str(node.get("id", "")), *[str(v) for v in node.get("class", [])]]
    ).lower()
    if attr == "href":
        return "链接"
    if attr == "src":
        return "图片"
    if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"} or re.search(
        r"title|heading", semantic
    ):
        return "标题"
    if re.search(r"price|amount|cost", semantic):
        return "价格"
    if re.search(r"author|writer|byline", semantic):
        return "作者"
    if node.name == "time" or re.search(r"date|time|publish", semantic):
        return "日期"
    if re.search(r"tag|category|label", semantic):
        return "标签"
    if re.search(r"name", semantic):
        return "名称"
    if re.search(r"desc|summary|content|text|intro", semantic):
        return "内容"
    if node.name == "a":
        return "链接文字"
    return "字段"


def _auto_field_priority(node, attr: str, name: str) -> int:
    if node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return 100
    if name in {"标题", "名称", "价格", "作者", "日期", "内容"}:
        return 90
    if attr in {"href", "src"}:
        return 75
    if node.name == "time":
        return 80
    if node.name == "p":
        return 55
    if node.name == "a":
        return 45
    if node.name in {"span", "strong", "small", "em"}:
        return 40
    return 25


def _auto_candidate_nodes(item) -> list:
    nodes = []
    seen: set[int] = set()
    for node in item.find_all(_AUTO_LEAF_TAGS):
        if _auto_hidden(node) or id(node) in seen:
            continue
        if node.name in _AUTO_TEXT_TAGS and node.name not in {"time"}:
            if node.find(list(_AUTO_LEAF_TAGS - {"div"}), recursive=True):
                continue
        text = _collapse(node.get_text(" ", strip=True))
        if node.name != "img" and not text:
            continue
        nodes.append(node)
        seen.add(id(node))
    return nodes


def _covered_by(value: str, existing: list[str]) -> bool:
    """新文本值是否只是已有字段文本的重复拼接（例如 <a><p>标题</p><span>日期</span></a>）。"""
    residual = value
    for old in existing:
        if not old:
            continue
        if old in residual:
            residual = residual.replace(old, " ")
        elif residual in old:
            residual = ""  # 新字段只是已有字段的一部分
            break
    return len(_collapse(residual)) <= 2


def _infer_auto_fields(items: list) -> tuple[list[dict], float]:
    sample = items[:12]
    candidates: dict[tuple[str, str], dict] = {}
    for item in sample:
        for node in _auto_candidate_nodes(item):
            selector = _auto_relative_selector(item, node)
            specs = [("text", _auto_field_name(node, "text"))]
            if node.name == "a" and node.get("href"):
                specs.append(("href", "链接"))
            if node.name == "img" and node.get("src"):
                specs.append(("src", "图片"))
            for attr, name in specs:
                key = (selector, attr)
                candidates.setdefault(
                    key,
                    {
                        "name": name,
                        "selector": selector,
                        "attr": attr,
                        "priority": _auto_field_priority(node, attr, name),
                    },
                )

    accepted = []
    for spec in candidates.values():
        values = []
        for item in sample:
            try:
                node = item.select_one(spec["selector"])
            except Exception:
                node = None
            if node is None:
                values.append("")
                continue
            if spec["attr"] == "text":
                values.append(_collapse(node.get_text(" ", strip=True)))
            else:
                values.append(str(node.get(spec["attr"], "") or ""))
        coverage = sum(bool(value) for value in values) / max(len(sample), 1)
        if coverage < 0.6:
            continue
        spec["coverage"] = coverage
        spec["values"] = values
        accepted.append(spec)

    accepted.sort(
        key=lambda spec: (-spec["priority"], -spec["coverage"], spec["selector"], spec["attr"])
    )
    fields: list[dict] = []
    field_values: list[list[str]] = []
    text_signatures: list[tuple[str, ...]] = []
    text_value_lists: list[list[str]] = []
    text_selectors: list[str] = []
    coverages: list[float] = []
    for spec in accepted:
        values = spec["values"]
        nonempty = [value for value in values if value]
        if not nonempty:
            continue
        # 多个条目中几乎不变的文本（固定标签、图标文案）没有采集价值
        if len(nonempty) >= 3 and len(set(nonempty)) / len(nonempty) < 0.3:
            continue
        if spec["attr"] == "text":
            signature = tuple(values)
            if any(signature == old for old in text_signatures):
                continue
            # 子节点字段比父节点更具体，先保留，稍后删除可被完全还原的父字段
            is_nested = any(
                _selector_descendant(spec["selector"], old) for old in text_selectors
            )
            if text_value_lists and not is_nested:
                covered = sum(
                    1
                    for index, value in enumerate(values)
                    if not value
                    or _covered_by(value, [old[index] for old in text_value_lists])
                )
                if covered / len(values) >= 0.8:
                    continue  # 父节点文本只是子字段的重复拼接
            text_signatures.append(signature)
            text_value_lists.append(values)
            text_selectors.append(spec["selector"])
        if spec["attr"] in {"href", "src"} and any(
            field["attr"] == spec["attr"] for field in fields
        ):
            continue  # 一个条目通常只需要一个详情链接 / 一张主图
        fields.append({
            "name": spec["name"],
            "selector": spec["selector"],
            "attr": spec["attr"],
        })
        field_values.append(values)
        coverages.append(spec["coverage"])
        if len(fields) >= 6:
            break

    # 删除可由子字段完整拼出的父节点文本（例如 <a><p>标题</p><span>日期</span></a> 的 a 文本）
    keep = [True] * len(fields)
    for index, field in enumerate(fields):
        if field["attr"] != "text":
            continue
        children = [
            child
            for child in range(len(fields))
            if child != index
            and fields[child]["attr"] == "text"
            and _selector_descendant(fields[child]["selector"], field["selector"])
        ]
        if not children:
            continue
        covered = sum(
            1
            for row, value in enumerate(field_values[index])
            if not value
            or _covered_by(value, [field_values[child][row] for child in children])
        )
        if covered / max(len(field_values[index]), 1) >= 0.8:
            keep[index] = False
    if not all(keep):
        fields = [field for index, field in enumerate(fields) if keep[index]]
        field_values = [
            values for index, values in enumerate(field_values) if keep[index]
        ]
        coverages = [value for index, value in enumerate(coverages) if keep[index]]

    date_pattern = re.compile(r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}|\d{1,2}:\d{2}")
    for field, values in zip(fields, field_values):
        if field["attr"] != "text":
            continue
        nonempty = [value for value in values if value]
        if nonempty and sum(
            bool(date_pattern.search(value)) for value in nonempty
        ) / len(nonempty) >= 0.7:
            field["name"] = "日期"

    if fields and not any(field["name"] == "标题" for field in fields):
        text_fields = [
            (field, values)
            for field, values in zip(fields, field_values)
            if field["attr"] == "text"
            and field["name"] in {"字段", "链接文字", "内容"}
        ]
        if text_fields:
            field, values = max(
                text_fields,
                key=lambda pair: sum(len(value) for value in pair[1])
                / max(len(pair[1]), 1),
            )
            average_length = sum(len(value) for value in values) / max(len(values), 1)
            if average_length >= 4 and field["name"] in {"字段", "链接文字", "内容"}:
                field["name"] = "标题"
    return fields, (sum(coverages) / len(coverages) if coverages else 0.0)


def _selector_descendant(selector: str, ancestor: str) -> bool:
    return bool(ancestor) and (
        selector.startswith(ancestor + " > ") or selector.startswith(ancestor + " ")
    )


def _best_auto_table(html: str) -> tuple[Extraction, dict] | None:
    best = None
    for table in parse_tables(html):
        row_count = len(table.rows)
        column_count = len(table.headers)
        if row_count < 2 or column_count < 2:
            continue
        cells = [cell for row in table.rows for cell in row]
        if not cells:
            continue
        nonempty = sum(bool(cell.strip()) for cell in cells) / len(cells)
        if nonempty < 0.2:
            continue
        widths = [sum(bool(cell.strip()) for cell in row) for row in table.rows]
        common_width = statistics.mode(widths)
        consistency = sum(width == common_width for width in widths) / len(widths)
        first_values = [row[0].strip() for row in table.rows if row and row[0].strip()]
        uniqueness = len(set(first_values)) / len(first_values) if first_values else 0.0
        score = (
            0.25 * min(row_count / 5, 1)
            + 0.15 * min((column_count - 1) / 3, 1)
            + 0.20 * nonempty
            + 0.15 * consistency
            + 0.10 * float(table.has_thead)
            + 0.15 * uniqueness
        )
        average_length = sum(len(cell) for cell in cells) / len(cells)
        if average_length > 300:
            score -= 0.15
        score = max(0.0, min(score, 1.0))
        if best is None or score > best[0]:
            best = (score, table)
    if best is None:
        return None

    score, table = best
    first_row_header = False
    if not table.has_thead and len(table.rows) >= 3:
        first = table.rows[0]
        unique_first = len(set(first)) == len(first)
        numeric_evidence = False
        for index, value in enumerate(first):
            later = [row[index] for row in table.rows[1:] if index < len(row) and row[index]]
            if value or not later:
                if value and not _looks_numeric(value) and later:
                    numeric_ratio = sum(_looks_numeric(cell) for cell in later) / len(later)
                    numeric_evidence = numeric_evidence or numeric_ratio >= 0.7
        first_row_header = bool(
            all(first) and unique_first and numeric_evidence
        )
    extraction = extract_table(
        parse_tables(html), table_index=table.index, first_row_header=first_row_header
    )
    return extraction, {
        "mode": "table",
        "score": round(score, 3),
        "reason": f"检测到 {len(table.rows)} 行 × {len(table.headers)} 列的数据表",
        "table_index": table.index,
        "first_row_header": first_row_header,
    }


def _looks_numeric(value: str) -> bool:
    value = value.strip()
    return bool(
        re.search(r"\d", value)
        and re.fullmatch(r"[\d\s,.%+\-−–—/():：￥¥$€]+", value)
    )


# ------------------------------------------------------------------ 结构化数据
_JSONLD_TYPES = {
    "Product",
    "Article",
    "NewsArticle",
    "BlogPosting",
    "Report",
    "Recipe",
    "JobPosting",
    "Event",
    "Course",
    "Book",
    "Movie",
    "VideoObject",
    "SoftwareApplication",
    "LocalBusiness",
    "Restaurant",
}
_KEY_NAMES = {
    "name": "名称",
    "title": "标题",
    "headline": "标题",
    "url": "链接",
    "link": "链接",
    "href": "链接",
    "date": "日期",
    "datepublished": "日期",
    "publishedat": "日期",
    "published_at": "日期",
    "publishtime": "日期",
    "price": "价格",
    "description": "摘要",
    "summary": "摘要",
    "author": "作者",
    "image": "图片",
    "img": "图片",
    "category": "分类",
    "tag": "标签",
    "tags": "标签",
    "content": "内容",
    "position": "序号",
}
_JS_ASSIGN = re.compile(
    r"window\.(__INITIAL_STATE__|__NUXT__|__DATA__|__PRELOADED_STATE__)\s*=\s*",
    re.IGNORECASE,
)


def _friendly_column(key: str) -> str:
    return _KEY_NAMES.get(key.split(".")[-1].lower(), key[:60])


def _scalar_text(value, key: str, base_url: str) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return ""
    text = _collapse(value)
    if text and key.split(".")[-1].lower() in {"url", "link", "href", "src"}:
        text = urljoin(base_url, text)
    return text[:2000]


def _flatten_record(
    record: dict, base_url: str, prefix: str = "", depth: int = 0, out: dict | None = None
) -> dict[str, str]:
    out = {} if out is None else out
    for key, value in record.items():
        if str(key).startswith("@") or value is None:
            continue
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            if depth < 2:
                _flatten_record(value, base_url, f"{name}.", depth + 1, out)
        elif isinstance(value, list):
            dicts = [item for item in value if isinstance(item, dict)]
            if dicts and depth < 2:
                _flatten_record(dicts[0], base_url, f"{name}.", depth + 1, out)
            else:
                text = "；".join(
                    item
                    for item in (_scalar_text(v, key, base_url) for v in value)
                    if item
                )
                if text:
                    out[name] = text[:2000]
        else:
            text = _scalar_text(value, key, base_url)
            if text:
                out[name] = text
    return out


def _records_to_extraction(
    records: list, base_url: str
) -> Extraction | None:
    flattened = [
        _flatten_record(record, base_url)
        for record in records[:2000]
        if isinstance(record, dict)
    ]
    flattened = [record for record in flattened if record]
    if not flattened:
        return None
    columns: list[str] = []
    for record in flattened:
        for key in record:
            if key not in columns:
                columns.append(key)
    if len(columns) < 2:
        return None
    columns = columns[:12]
    rows = [[record.get(key, "") for key in columns] for record in flattened]
    return Extraction(
        columns=_unique_columns([_friendly_column(key) for key in columns]),
        rows=rows,
    )


def _iter_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_dicts(child)


def _jsonld_candidates(soup: BeautifulSoup) -> list[tuple[float, list, str]]:
    import json

    candidates: list[tuple[float, list, str]] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw or len(raw) > 2_000_000:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for obj in _iter_dicts(payload):
            raw_types = obj.get("@type")
            types = {raw_types} if isinstance(raw_types, str) else set(raw_types or [])
            if "ItemList" in types:
                items = []
                for element in obj.get("itemListElement") or []:
                    if not isinstance(element, dict):
                        continue
                    if isinstance(element.get("item"), dict):
                        item = dict(element["item"])
                        for key in ("url", "name"):
                            if element.get(key):
                                item.setdefault(key, element[key])
                        items.append(item)
                    else:
                        items.append(element)
                if len(items) >= 2:
                    score = min(0.9, 0.68 + 0.02 * min(len(items), 10))
                    candidates.append((score, items, "JSON-LD 列表数据"))
            elif types & _JSONLD_TYPES:
                fields = _flatten_record(obj, "")
                if len(fields) >= 2:
                    # 单条 JSON-LD 常是站点自身介绍，置信度要低于真实列表/正文
                    score = min(0.78, 0.4 + 0.025 * min(len(fields), 10))
                    candidates.append((score, [obj], "JSON-LD 结构化数据"))
    return candidates


def _json_payloads(soup: BeautifulSoup):
    import json

    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw or len(raw) > 2_000_000:
            continue
        script_id = str(script.get("id") or "")
        script_type = str(script.get("type") or "").lower()
        payload = None
        if script_id in {"__NEXT_DATA__", "__NUXT_DATA__"} or script_type in {
            "application/json",
            "application/ld+json",
        }:
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                payload = None
        elif "window." in raw:
            match = _JS_ASSIGN.search(raw)
            if match:
                tail = raw[match.end():].strip().rstrip(";")
                try:
                    payload = json.loads(tail)
                except (ValueError, TypeError):
                    payload = None
        if payload is not None:
            yield payload


def _record_lists(value, depth: int = 0) -> list[tuple[float, list]]:
    found: list[tuple[float, list]] = []
    if depth > 6:
        return found
    if isinstance(value, dict):
        for child in value.values():
            found.extend(_record_lists(child, depth + 1))
    elif isinstance(value, list):
        dicts = [item for item in value if isinstance(item, dict)]
        if len(value) >= 3 and len(dicts) / len(value) >= 0.8:
            flattened = [_flatten_record(item, "") for item in dicts[:30]]
            columns = set().union(*flattened) if flattened else set()
            rich = sum(len(record) >= 2 for record in flattened) / max(len(flattened), 1)
            if len(columns) >= 2 and rich >= 0.6:
                keywords = {"name", "title", "url", "link", "price", "date", "content"}
                bonus = 0.03 * bool(keywords & {key.split(".")[-1].lower() for key in columns})
                score = min(
                    0.9,
                    0.55
                    + 0.015 * min(len(value), 15)
                    + 0.015 * min(len(columns), 8)
                    + bonus,
                )
                found.append((score, value))
        for child in value:
            found.extend(_record_lists(child, depth + 1))
    return found


def extract_structured(html: str, base_url: str) -> tuple[Extraction, dict] | None:
    """从 JSON-LD、__NEXT_DATA__、内嵌 state 等数据源提取结构化记录。"""
    soup = make_soup(html)
    candidates = list(_jsonld_candidates(soup))
    for payload in _json_payloads(soup):
        for score, records in _record_lists(payload):
            candidates.append((score, records, "页面内嵌 JSON 数据"))
    best = None
    for score, records, reason in candidates:
        extraction = _records_to_extraction(records, base_url)
        if extraction and (best is None or score > best[0]):
            best = (score, extraction, reason, len(extraction.rows))
    if best is None:
        return None
    score, extraction, reason, count = best
    return extraction, {
        "mode": "structured",
        "score": round(score, 3),
        "reason": f"{reason}：{count} 条记录",
    }


def frame_sources(html: str, base_url: str) -> list[tuple[str, str]]:
    """返回页面内 frame / iframe 的 (name, 绝对地址)，用于跟进年鉴等框架目录页。"""
    soup = make_soup(html)
    frames = []
    for frame in soup.find_all(["frame", "iframe"]):
        src = str(frame.get("src") or "").strip()
        if src:
            frames.append((str(frame.get("name") or ""), urljoin(base_url, src)))
    return frames


def looks_like_js_shell(html: str) -> bool:
    soup = make_soup(html)
    scripts = len(soup.find_all("script"))
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = _collapse(soup.get_text(" ", strip=True))
    return scripts >= 2 and len(text) < 200


def extract_feed(xml_text: str, base_url: str) -> tuple[Extraction, dict]:
    """解析 RSS / Atom，输出标题、链接、日期、摘要、作者。"""
    import xml.etree.ElementTree as ET

    try:
        clean = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml_text)
        root = ET.fromstring(clean)
    except ET.ParseError as exc:
        raise ExtractionError(f"Feed 解析失败：{exc}") from exc

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].lower()

    items = [node for node in root.iter() if local(node.tag) in {"item", "entry"}]
    rows: list[list[str]] = []
    for item in items[:500]:
        values: dict[str, str] = {}
        link = ""
        for child in item:
            name = local(child.tag)
            text = _collapse(child.text or "") or _collapse(
                "".join(child.itertext())
            )
            if name == "link":
                link = link or str(child.get("href") or text)
            elif name in {"title", "pubdate", "published", "updated", "description", "summary"}:
                values.setdefault(name, text)
            elif name in {"creator", "author"}:
                values.setdefault("author", text)
        if link:
            link = urljoin(base_url, link)
        title = values.get("title", "")
        date = values.get("pubdate") or values.get("published") or values.get("updated", "")
        summary = values.get("description") or values.get("summary", "")
        author = values.get("author", "")
        if title or link:
            rows.append([title, link, date, summary[:1000], author])
    if not rows:
        raise ExtractionError("Feed 中没有找到条目")
    return Extraction(columns=["标题", "链接", "日期", "摘要", "作者"], rows=rows), {
        "mode": "feed",
        "score": 0.95,
        "reason": f"识别为 RSS / Atom 订阅源：{len(rows)} 条",
    }





def _best_auto_list(
    html: str, base_url: str, *, relaxed: bool = False
) -> tuple[Extraction, dict] | None:
    soup = make_soup(html)
    best = None
    sim_threshold = 0.45 if relaxed else 0.55
    parents = soup.find_all(True)[:800]
    for parent in parents:
        if parent.name in {"table", "tr", "tbody", "thead", "tfoot"}:
            continue
        if _auto_blocked(parent):
            continue
        children = [
            child for child in parent.find_all(recursive=False)
            if not _auto_hidden(child)
        ]
        if len(children) < 3:
            continue
        groups: dict[str, list] = {}
        for child in children:
            # 同时按标签名和共享 class 分组，覆盖 SPA 中同类卡片用不同标签包裹的情况
            groups.setdefault(f"tag:{child.name}", []).append(child)
            for cls in child.get("class", []):
                cls = str(cls)
                if cls and _safe_css_ident(cls):
                    groups.setdefault(f"class:{cls}", []).append(child)
        for key, items in groups.items():
            if len(items) < 3 or len(items) / len(children) < 0.4:
                continue
            if any(_auto_blocked(item) for item in items):
                continue
            sample = items[:12]
            signatures = [_structure_signature(item) for item in sample]
            if not any(signatures):
                continue
            medoid = max(
                signatures,
                key=lambda signature: sum(
                    _jaccard(signature, other) for other in signatures
                ),
            )
            similarities = [_jaccard(medoid, signature) for signature in signatures]
            median_similarity = statistics.median(similarities)
            if median_similarity < sim_threshold:
                continue
            min_sim_ratio = 0.6 if relaxed else 0.7
            if sum(value >= 0.5 for value in similarities) / len(similarities) < min_sim_ratio:
                continue

            common_classes = set(str(v) for v in items[0].get("class", []))
            for item in items[1:]:
                common_classes.intersection_update(str(v) for v in item.get("class", []))
            common_classes = {value for value in common_classes if _safe_css_ident(value)}
            if key.startswith("class:"):
                # 按共享 class 分组时，直接用该 class 作为条目选择器（不依赖标签名）
                item_part = f".{key.split(':', 1)[1]}"
            else:
                tag_name = key.split(":", 1)[1]
                item_part = tag_name + "".join(f".{value}" for value in sorted(common_classes))
            selector = f"{_auto_parent_selector(parent, soup)} > {item_part}"
            try:
                matched = soup.select(selector)
            except Exception:
                continue
            original_count = sum(any(node is item for item in items) for node in matched)
            # 目录页常重复使用同一个 id（如多个 ul#foldinglist），选择器会合并所有章节；
            # 只要原始条目都被覆盖且数量可控，就接受这种“超集”匹配。
            if original_count / len(items) < 0.8 or len(matched) > 5000:
                continue

            fields, field_coverage = _infer_auto_fields(items)
            if not fields:
                continue
            try:
                extraction = extract_css(html, base_url, selector, fields)
            except ExtractionError:
                continue
            texts = [_collapse(item.get_text(" ", strip=True)) for item in sample]
            unique_ratio = len(set(texts)) / len(texts) if texts else 0.0
            average_length = sum(len(text) for text in texts) / max(len(texts), 1)
            score = (
                0.25 * min(len(items) / 5, 1)
                + 0.20 * median_similarity
                + 0.20 * field_coverage
                + 0.15 * unique_ratio
                + 0.10 * min(len(fields) / 3, 1)
                + 0.10 * (len(items) / len(children))
            )
            simple_links = all(signature <= {"a"} for signature in signatures)
            if simple_links:
                score -= 0.25
            if average_length < 8:
                score -= 0.15
            links_per_item = statistics.median(
                len(item.find_all("a")) for item in sample
            )
            if links_per_item > 3:
                score -= 0.3  # 条目本身是一整块目录容器，不是一行数据
            if average_length > 300:
                score -= 0.2
            score = max(0.0, min(score, 1.0))
            if best is None or score > best[0]:
                best = (score, extraction, selector, fields, len(items), median_similarity)
    if best is None:
        return None
    score, extraction, selector, fields, count, similarity = best
    return extraction, {
        "mode": "css",
        "score": round(score, 3),
        "reason": f"检测到 {count} 个结构相似的重复条目",
        "item_selector": selector,
        "item_selector_type": "css",
        "fields": fields,
        "similarity": round(similarity, 3),
    }


def extract_json_payloads(
    payloads: list, base_url: str
) -> tuple[Extraction, dict] | None:
    """从浏览器运行时捕获的 XHR / fetch JSON 响应中识别记录列表。

    很多动态页把真实数据放在接口响应里，渲染后的 DOM 只是其中一部分；
    直接解析接口数据通常比从 DOM 猜结构更准确。
    """
    best = None
    for payload in payloads[:20]:
        for score, records in _record_lists(payload):
            extraction = _records_to_extraction(records, base_url)
            if extraction and (best is None or score > best[0]):
                best = (score, extraction, len(records))
    if best is None:
        return None
    score, extraction, count = best
    return extraction, {
        "mode": "network",
        "score": round(min(score + 0.03, 0.95), 3),
        "reason": f"浏览器网络 JSON：{count} 条记录",
    }


def extract_auto(
    html: str,
    base_url: str,
    rule: dict | None = None,
    *,
    browser_rendered: bool = False,
    json_payloads: list | None = None,
) -> tuple[Extraction, dict]:
    """智能识别表格、重复列表或正文；后续页可复用第一页规则。"""
    if rule and rule.get("mode") == "network":
        network = extract_json_payloads(json_payloads or [], base_url)
        if network is not None:
            return network[0], rule
        rule = None  # 后续页没有捕获到网络数据，退化为自动识别

    if rule:
        mode = rule.get("mode")
        if mode == "table":
            extraction = extract_table(
                parse_tables(html),
                table_index=rule.get("table_index"),
                first_row_header=bool(rule.get("first_row_header")),
            )
        elif mode == "css":
            extraction = extract_css(
                html,
                base_url,
                str(rule.get("item_selector", "")),
                list(rule.get("fields", [])),
                item_selector_type=str(rule.get("item_selector_type", "css")),
            )
        elif mode == "article":
            extraction = extract_article(html, base_url)
        elif mode == "structured":
            structured = extract_structured(html, base_url)
            if structured is None:
                raise ExtractionError("后续页未找到与第一页相同的结构化数据")
            extraction = structured[0]
        else:
            raise ExtractionError("自动识别规则无效，请重新抓取第一页")
        return extraction, rule

    soup = make_soup(html)
    if soup.find("frameset"):
        raise ExtractionError(
            "这是框架目录页，请打开具体框架页面；若统计表是图片，请直接输入图片 URL"
        )

    # 列表页信号：链接较多（含文字）时，大概率是列表/目录，不是单篇正文
    text_links = sum(
        1 for a in soup.find_all("a") if _collapse(a.get_text(" ", strip=True))
    )
    is_list_like = text_links >= 15

    candidates: list[tuple[Extraction, dict]] = []
    table_candidate = _best_auto_table(html)
    if table_candidate:
        candidates.append(table_candidate)
    try:
        list_candidate = _best_auto_list(html, base_url, relaxed=browser_rendered)
    except ExtractionError:
        list_candidate = None
    if list_candidate:
        candidates.append(list_candidate)

    # 用 readability 剥离导航/侧栏/广告后，在主内容容器里再做一次列表识别。
    # 很多页面的列表被周围导航项干扰（导航也是结构相似的重复块），清洗后能更准。
    cleaned_list_candidate = None
    cleaned_html = _main_content_html(html, base_url)
    if cleaned_html and cleaned_html != html and len(cleaned_html) < len(html):
        try:
            cleaned_list_candidate = _best_auto_list(
                cleaned_html, base_url, relaxed=browser_rendered
            )
        except ExtractionError:
            cleaned_list_candidate = None
        if cleaned_list_candidate:
            # 清洗后的候选只有在分数更高或条目更纯时才采用，避免 readability 误删内容
            list_score = list_candidate[1]["score"] if list_candidate else 0.0
            if (
                cleaned_list_candidate[1]["score"] > list_score
                or (list_candidate and len(cleaned_list_candidate[0].rows) > len(list_candidate[0].rows))
            ):
                cleaned_list_candidate[1]["reason"] = (
                    cleaned_list_candidate[1]["reason"] + "（已剥离页面导航/侧栏）"
                )
                candidates.append(cleaned_list_candidate)

    structured_candidate = None
    try:
        structured_candidate = extract_structured(html, base_url)
    except Exception:
        structured_candidate = None
    if structured_candidate:
        candidates.append(structured_candidate)

    network_candidate = None
    if json_payloads:
        try:
            network_candidate = extract_json_payloads(json_payloads, base_url)
        except Exception:
            network_candidate = None
        if network_candidate:
            candidates.append(network_candidate)

    article_candidate = None
    article_score = 0.0
    try:
        article = extract_article(html, base_url, browser_rendered=browser_rendered)
        body = article.rows[0][-1] if article.rows else ""
        article_score = min(len(body) / 600, 1) * 0.8 + 0.2 * bool(article.rows[0][0])
        page_text = _collapse(soup.get_text(" ", strip=True))
        link_text = sum(
            len(_collapse(link.get_text(" ", strip=True)))
            for link in soup.find_all("a")
        )
        if page_text and link_text / len(page_text) >= 0.5:
            article_score *= 0.6  # 链接目录页，不应被当成正文
        if is_list_like:
            article_score *= 0.5  # 明显的列表页，正文模式降权
        article_candidate = (article, {
            "mode": "article",
            "score": round(article_score, 3),
            "reason": f"检测到约 {len(body)} 字的正文内容",
        })
    except (ExtractionError, IndexError):
        pass

    best_structured = max(candidates, key=lambda item: item[1]["score"]) if candidates else None
    low_confidence = False
    # 浏览器渲染后的页面通常是应用/列表页：只要列表/结构化/表格候选分数够，就优先于正文
    if best_structured and best_structured[1]["score"] >= 0.60:
        extraction, detected = best_structured
    elif (
        browser_rendered
        and best_structured
        and best_structured[1]["score"] >= 0.40
        and (list_candidate or structured_candidate or network_candidate)
    ):
        # 渲染页：列表/结构化分数超过 0.4 即优先，避免正文把列表数据吞掉
        extraction, detected = best_structured
        if best_structured[1]["score"] < 0.55:
            low_confidence = True
    elif article_candidate and article_score >= 0.55:
        extraction, detected = article_candidate
    elif best_structured and best_structured[1]["score"] >= 0.45:
        extraction, detected = best_structured
        low_confidence = True
    elif article_candidate and article_candidate[0].rows[0][-1].strip():
        extraction, detected = article_candidate
        low_confidence = True
    elif looks_like_js_shell(html):
        raise ExtractionError(
            "页面正文由 JavaScript 动态渲染，静态抓取没有内容。"
            "启动参数中已支持浏览器渲染；若未安装 Playwright，请执行 "
            "pip install playwright 与 python -m playwright install chromium"
        )
    else:
        raise ExtractionError(
            "未能自动识别有效数据。若是 JS 动态页面请尝试浏览器渲染；"
            "若仍失败，请在高级设置中手动指定提取规则"
        )

    detected = dict(detected)
    detected["candidates"] = {
        "table": table_candidate[1]["score"] if table_candidate else 0,
        "list": list_candidate[1]["score"] if list_candidate else 0,
        "structured": structured_candidate[1]["score"] if structured_candidate else 0,
        "network": network_candidate[1]["score"] if network_candidate else 0,
        "article": round(article_score, 3),
    }
    if low_confidence:
        detected["low_confidence"] = True
        extraction.warnings.append("自动识别置信度较低，请核对预览；不准确时请使用高级模式")
    return extraction, detected


def normalize_rule(rule: dict | None) -> dict | None:
    """校验前端回传 / 历史复用的人工提取规则，防止非法结构进入执行环节。"""
    if rule is None:
        return None
    if not isinstance(rule, dict):
        raise ExtractionError("提取规则格式无效")
    mode = str(rule.get("mode") or "").strip().lower()
    if not mode:
        return None
    if mode not in {"table", "css", "article", "structured"}:
        raise ExtractionError("提取规则 mode 无效")
    normalized: dict = {"mode": mode}
    if mode == "table":
        index = rule.get("table_index")
        try:
            normalized["table_index"] = int(index) if index is not None else None
        except (TypeError, ValueError):
            normalized["table_index"] = None
        normalized["first_row_header"] = bool(rule.get("first_row_header"))
        return normalized
    if mode == "css":
        item_selector = str(rule.get("item_selector") or "").strip()
        if not item_selector:
            raise ExtractionError("CSS 规则缺少条目选择器")
        if len(item_selector) > 500:
            raise ExtractionError("条目选择器过长")
        item_kind = str(rule.get("item_selector_type") or "css").strip().lower()
        if item_kind not in {"css", "xpath"}:
            item_kind = "css"
        raw_fields = rule.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ExtractionError("CSS 规则至少需要一个字段映射")
        fields: list[dict] = []
        for spec in raw_fields[:30]:
            if not isinstance(spec, dict):
                raise ExtractionError("字段映射格式无效")
            name = str(spec.get("name") or "").strip()[:60]
            if not name:
                raise ExtractionError("字段名不能为空")
            selector = str(spec.get("selector") or "").strip()[:500]
            attr = (str(spec.get("attr") or "text").strip()[:30] or "text")
            field_kind = str(spec.get("selector_type") or item_kind).strip().lower()
            if field_kind not in {"css", "xpath"}:
                field_kind = item_kind
            fields.append(
                {
                    "name": name,
                    "selector": selector,
                    "attr": attr,
                    "selector_type": field_kind,
                }
            )
        normalized.update(
            item_selector=item_selector,
            item_selector_type=item_kind,
            fields=fields,
        )
    return normalized


def build_schema(
    extraction: Extraction, detected: dict | None, *, source_url: str = ""
) -> dict:
    """输出可复用的提取 schema（列定义 + 选择器），便于保存、校验与再次执行。"""
    detected = dict(detected or {})
    mode = str(detected.get("mode") or "auto")
    fields: list[dict] = []
    if mode == "css" and isinstance(detected.get("fields"), list):
        for spec in detected["fields"][:30]:
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or "").strip()[:60]
            if not name:
                continue
            fields.append(
                {
                    "name": name,
                    "selector": str(spec.get("selector") or "")[:500],
                    "attr": str(spec.get("attr") or "text")[:30],
                    "selector_type": str(spec.get("selector_type") or "css")[:10],
                }
            )
    if not fields:
        fields = [
            {
                "name": column,
                "selector": "",
                "attr": "text",
                "selector_type": "css",
            }
            for column in extraction.columns
        ]
    return {
        "version": 1,
        "source_url": source_url,
        "mode": mode,
        "item_selector": str(detected.get("item_selector") or ""),
        "item_selector_type": str(detected.get("item_selector_type") or "css"),
        "table_index": detected.get("table_index"),
        "first_row_header": bool(detected.get("first_row_header")),
        "fields": fields,
        "columns": list(extraction.columns),
        "score": detected.get("score"),
    }


def analyze_page(html: str, url: str, *, json_payloads: list | None = None) -> dict:
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

    schema = None
    try:
        auto_extraction, auto_rule = extract_auto(
            html, url, json_payloads=json_payloads
        )
        schema = build_schema(auto_extraction, auto_rule, source_url=url)
        auto_summary = {
            **auto_rule,
            "rows": len(auto_extraction.rows),
            "columns": auto_extraction.columns,
            "preview": auto_extraction.rows[:3],
            "quality": auto_extraction.quality,
            "warnings": auto_extraction.warnings,
        }
    except ExtractionError as exc:
        auto_summary = {"mode": None, "error": str(exc)}

    title = _meta(soup, "og:title") or ""
    if not title:
        h1 = soup.find("h1")
        title = _collapse(h1.get_text(" ", strip=True)) if h1 else ""
    if not title and soup.title:
        title = _collapse(soup.title.get_text(" ", strip=True))

    return {
        "title": title,
        "url": url,
        "auto": auto_summary,
        "schema": schema,
        "tables": [
            {
                "index": t.index,
                "rows": len(t.rows),
                "cols": len(t.headers),
                "headers": t.headers[:30],
                "header_rows": t.header_rows,
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
