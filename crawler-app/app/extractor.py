"""页面解析：自动表格、CSS 选择器、正文抽取三种模式。"""

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
            row.append(_dedupe_repeated(_collapse(value)))
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





def _best_auto_list(html: str, base_url: str) -> tuple[Extraction, dict] | None:
    soup = make_soup(html)
    best = None
    parents = soup.find_all(True)[:400]
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
            groups.setdefault(child.name, []).append(child)
        for tag_name, items in groups.items():
            if len(items) < 3 or len(items) / len(children) < 0.5:
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
            if median_similarity < 0.55:
                continue
            if sum(value >= 0.5 for value in similarities) / len(similarities) < 0.7:
                continue

            common_classes = set(str(v) for v in items[0].get("class", []))
            for item in items[1:]:
                common_classes.intersection_update(str(v) for v in item.get("class", []))
            common_classes = {value for value in common_classes if _safe_css_ident(value)}
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
        "fields": fields,
        "similarity": round(similarity, 3),
    }


def extract_auto(
    html: str, base_url: str, rule: dict | None = None
) -> tuple[Extraction, dict]:
    """智能识别表格、重复列表或正文；后续页可复用第一页规则。"""
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

    candidates: list[tuple[Extraction, dict]] = []
    table_candidate = _best_auto_table(html)
    if table_candidate:
        candidates.append(table_candidate)
    try:
        list_candidate = _best_auto_list(html, base_url)
    except ExtractionError:
        list_candidate = None
    if list_candidate:
        candidates.append(list_candidate)

    structured_candidate = None
    try:
        structured_candidate = extract_structured(html, base_url)
    except Exception:
        structured_candidate = None
    if structured_candidate:
        candidates.append(structured_candidate)

    article_candidate = None
    article_score = 0.0
    try:
        article = extract_article(html, base_url)
        body = article.rows[0][-1] if article.rows else ""
        article_score = min(len(body) / 600, 1) * 0.8 + 0.2 * bool(article.rows[0][0])
        page_text = _collapse(soup.get_text(" ", strip=True))
        link_text = sum(
            len(_collapse(link.get_text(" ", strip=True)))
            for link in soup.find_all("a")
        )
        if page_text and link_text / len(page_text) >= 0.5:
            article_score *= 0.6  # 链接目录页，不应被当成正文
        article_candidate = (article, {
            "mode": "article",
            "score": round(article_score, 3),
            "reason": f"检测到约 {len(body)} 字的正文内容",
        })
    except (ExtractionError, IndexError):
        pass

    best_structured = max(candidates, key=lambda item: item[1]["score"]) if candidates else None
    low_confidence = False
    if best_structured and best_structured[1]["score"] >= 0.60:
        extraction, detected = best_structured
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
        "article": round(article_score, 3),
    }
    if low_confidence:
        detected["low_confidence"] = True
        extraction.warnings.append("自动识别置信度较低，请核对预览；不准确时请使用高级模式")
    return extraction, detected


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

    try:
        auto_extraction, auto_rule = extract_auto(html, url)
        auto_summary = {
            **auto_rule,
            "rows": len(auto_extraction.rows),
            "columns": auto_extraction.columns,
            "preview": auto_extraction.rows[:3],
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
