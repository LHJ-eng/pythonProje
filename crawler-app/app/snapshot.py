"""页面快照与可视化点选。

把抓取到的 HTML 清洗成可安全预览的快照（移除脚本 / 事件 / 外链样式），
并推断页面里的表格与重复列表候选，供前端在快照上点选后自动生成提取规则。

设计参考 EasySpider / Automa 的“可视化点选”思路：不引入浏览器扩展，
由服务端生成快照，前端在受限 iframe 中拦截点击并反推 CSS 选择器。
"""

from __future__ import annotations

import re
import statistics
from urllib.parse import urljoin

from .extractor import (
    ExtractionError,
    _auto_blocked,
    _auto_parent_selector,
    _collapse,
    _infer_auto_fields,
    _jaccard,
    _safe_css_ident,
    _structure_signature,
    extract_css,
    make_soup,
    table_matrix,
)

MAX_SNAPSHOT_CHARS = 2_000_000
MAX_TABLES = 12
MAX_LISTS = 6

_REMOVE_TAGS = {
    "script",
    "noscript",
    "object",
    "embed",
    "applet",
    "iframe",
    "frame",
    "frameset",
}
_SKIP_LINK_RELS = {
    "stylesheet",
    "preload",
    "prefetch",
    "dns-prefetch",
    "preconnect",
    "modulepreload",
    "manifest",
    "import",
}
_BAD_META_EQUIV = {"refresh", "set-cookie", "content-security-policy"}
_REVEAL_CSS = """
[hidden], [aria-hidden="true"] { display: revert !important; }
[style*="display:none"], [style*="display: none"] { display: revert !important; }
[style*="visibility:hidden"], [style*="visibility: hidden"] { visibility: visible !important; }
table, thead, tbody, tfoot, tr, td, th { display: revert !important; }
""".strip()

_HEADER_STYLE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
_HEADER_VIS = re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE)


# ---------------------------------------------------------------- 安全快照
def _ensure_head(soup):
    head = soup.head
    if head is not None:
        return head
    head = soup.new_tag("head")
    if soup.html is not None:
        soup.html.insert(0, head)
    else:
        first = soup.find(True)
        if first is not None:
            first.insert_before(head)
        else:
            soup.append(head)
    return head


def _sanitize_attributes(tag, base_url: str, reveal_hidden: bool) -> None:
    for attr in list(tag.attrs):
        lowered = str(attr).lower()
        if lowered.startswith("on") or lowered in {"srcdoc", "formaction"}:
            del tag.attrs[attr]
    for attr in ("href", "src", "action", "poster", "xlink:href"):
        if not tag.has_attr(attr):
            continue
        value = str(tag.get(attr) or "").strip()
        lowered = value.lower().replace(" ", "")
        if lowered.startswith(("javascript:", "vbscript:", "data:text/html")):
            if attr in {"href", "action"}:
                tag[attr] = "#"
            else:
                del tag.attrs[attr]
            continue
        if value and attr in {"href", "src", "poster"}:
            tag[attr] = urljoin(base_url, value)
    if tag.name == "form":
        tag["action"] = "#"
        tag["method"] = "get"
    if reveal_hidden:
        if tag.has_attr("hidden"):
            del tag.attrs["hidden"]
        if str(tag.get("aria-hidden", "")).lower() == "true":
            del tag.attrs["aria-hidden"]
        style = tag.get("style")
        if style:
            new_style = _HEADER_STYLE.sub("display: revert", str(style))
            new_style = _HEADER_VIS.sub("visibility: visible", new_style)
            tag["style"] = new_style


def sanitize_html(
    html: str,
    base_url: str = "",
    *,
    reveal_hidden: bool = True,
    max_chars: int = MAX_SNAPSHOT_CHARS,
) -> str:
    """生成可在 iframe 中安全预览的 HTML 快照。"""
    base_url = base_url or "https://example.com/"
    soup = make_soup(html)

    for tag in soup.find_all(list(_REMOVE_TAGS)):
        tag.decompose()
    for tag in soup.find_all("base"):
        tag.decompose()
    for tag in soup.find_all("link"):
        rel = " ".join(str(value).lower() for value in (tag.get("rel") or []))
        if not rel or any(item in rel for item in _SKIP_LINK_RELS):
            tag.decompose()
    for tag in soup.find_all("meta"):
        if str(tag.get("http-equiv", "")).lower() in _BAD_META_EQUIV:
            tag.decompose()
    for tag in soup.find_all(True):
        _sanitize_attributes(tag, base_url, reveal_hidden)

    head = _ensure_head(soup)
    if not head.find("meta", attrs={"charset": True}):
        head.insert(0, soup.new_tag("meta", charset="utf-8"))
    reveal = soup.new_tag("style")
    reveal["id"] = "dh-reveal"
    reveal.string = (
        _REVEAL_CSS
        if reveal_hidden
        else "table, thead, tbody, tfoot, tr, td, th { display: revert !important; }"
    )
    head.append(reveal)
    head.insert(0, soup.new_tag("base", href=base_url))

    text = str(soup)
    if not text.lstrip().lower().startswith("<!doctype"):
        text = "<!DOCTYPE html>\n" + text
    if len(text) <= max_chars:
        return text

    # 超限时先移除样式、内联大图，再从 body 末尾裁剪，保证仍可交互
    for tag in soup.find_all("style"):
        if tag.get("id") != "dh-reveal":
            tag.decompose()
    for tag in soup.find_all(["img", "source"]):
        for attr in ("src", "srcset", "data-src"):
            if str(tag.get(attr, "")).lower().startswith("data:"):
                del tag.attrs[attr]
    text = str(soup)
    if not text.lstrip().lower().startswith("<!doctype"):
        text = "<!DOCTYPE html>\n" + text
    body = soup.body
    while len(text) > max_chars and body is not None and len(body.contents) > 1:
        body.contents[-1].extract()
        text = str(soup)
        if not text.lstrip().lower().startswith("<!doctype"):
            text = "<!DOCTYPE html>\n" + text
    return text[:max_chars]


def page_title(html: str) -> str:
    soup = make_soup(html)
    for name in ("og:title", "twitter:title"):
        tag = soup.find("meta", attrs={"property": name}) or soup.find(
            "meta", attrs={"name": name}
        )
        if tag and tag.get("content"):
            return _collapse(str(tag["content"]))
    h1 = soup.find("h1")
    if soup.title:
        text = _collapse(soup.title.get_text(" ", strip=True))
        if text:
            return text
    if h1:
        text = _collapse(h1.get_text(" ", strip=True))
        if text:
            return text
    return ""


# ---------------------------------------------------------------- 公共工具
def _is_hidden(tag) -> bool:
    current = tag
    while current is not None and getattr(current, "name", None) not in (None, "[document]"):
        if getattr(current, "has_attr", None) and current.has_attr("hidden"):
            return True
        if str(current.get("aria-hidden", "")).lower() == "true":
            return True
        style = str(current.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return True
        current = current.parent
    return False


def _nth_of_type(tag) -> str:
    parent = tag.parent
    if parent is None:
        return tag.name
    siblings = parent.find_all(tag.name, recursive=False)
    try:
        index = siblings.index(tag) + 1
    except ValueError:
        index = 1
    return f"{tag.name}:nth-of-type({index})"


def css_path(tag, soup) -> str:
    """计算元素在文档中的稳定 CSS 路径（优先唯一 id，其次 class）。"""
    segments: list[str] = []
    current = tag
    while current is not None and getattr(current, "name", None) not in (None, "[document]"):
        if current.name == "body":
            segments.append("body")
            break
        ident = str(current.get("id", ""))
        if _safe_css_ident(ident):
            try:
                if len(soup.select(f"#{ident}")) == 1:
                    segments.append(f"#{ident}")
                    break
            except Exception:
                pass
        classes = [str(value) for value in current.get("class", []) if _safe_css_ident(str(value))]
        if classes:
            segments.append(current.name + "." + ".".join(classes[:2]))
        else:
            segments.append(_nth_of_type(current))
        current = current.parent
    return " > ".join(reversed(segments)) or "body"


# ---------------------------------------------------------------- 表格候选
def _table_rule(table, soup) -> dict:
    table_sel = css_path(table, soup)
    headers, rows, header_rows, cell_tag, _ = table_matrix(table)
    if not headers or not rows:
        return {}
    width = len(headers)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    if table.find("thead") is not None and table.find("tbody") is not None:
        item_selector = f"{table_sel} tbody tr"
    elif header_rows and table.find("thead") is None:
        # 表头来自首行（th 或首行内容）：跳过表头行，避免被当作数据
        item_selector = f"{table_sel} tr:nth-child(n+{header_rows + 1})"
    else:
        item_selector = f"{table_sel} tr"

    fields = [
        {
            "name": name,
            "selector": f"{cell_tag}:nth-child({index + 1})",
            "attr": "text",
            "selector_type": "css",
        }
        for index, name in enumerate(headers)
    ]
    return {
        "selector": table_sel,
        "item_selector": item_selector,
        "item_selector_type": "css",
        "headers": headers,
        "sample": normalized[:3],
        "rows": len(normalized),
        "cols": width,
        "fields": fields,
        "rule": {
            "mode": "css",
            "item_selector": item_selector,
            "item_selector_type": "css",
            "fields": fields,
        },
    }


def table_candidates(html: str, limit: int = MAX_TABLES) -> list[dict]:
    """返回页面内所有表格候选（包含隐藏 / 嵌套表格），按数据量排序。"""
    soup = make_soup(html)
    candidates: list[dict] = []
    for table in soup.find_all("table"):
        rule = _table_rule(table, soup)
        if not rule or not rule["rows"]:
            continue
        hidden = _is_hidden(table)
        nested = table.find_parent("table") is not None
        score = (
            0.5 * min(rule["rows"] / 10, 1)
            + 0.25 * min(rule["cols"] / 5, 1)
            + (0.1 if rule["headers"] and not rule["headers"][0].startswith("列") else 0)
            + (0.05 if not hidden else 0)
            - (0.1 if nested else 0)
        )
        candidates.append(
            {
                "kind": "table",
                **rule,
                "hidden": hidden,
                "nested": nested,
                "score": round(max(0.0, min(score, 1.0)), 3),
            }
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:limit]


# ---------------------------------------------------------------- 列表候选
def _list_fields(items: list) -> tuple[list[dict], float]:
    try:
        return _infer_auto_fields(items)
    except Exception:
        return [], 0.0


def list_candidates(
    html: str, base_url: str = "", limit: int = MAX_LISTS
) -> list[dict]:
    """推断重复列表 / 卡片候选（同 tag + 共享 class 的兄弟条目）。"""
    soup = make_soup(html)
    found: list[dict] = []
    seen: set[str] = set()
    seen_fingerprints: set[tuple[int, ...]] = set()
    for parent in soup.find_all(True)[:1000]:
        if parent.name in {"table", "tr", "tbody", "thead", "tfoot"}:
            continue
        if _auto_blocked(parent):
            continue
        children = [
            child for child in parent.find_all(recursive=False)
            if not _is_hidden(child)
        ]
        if len(children) < 3:
            continue
        groups: dict[str, list] = {}
        for child in children:
            groups.setdefault(f"tag:{child.name}", []).append(child)
            for cls in child.get("class", []):
                cls = str(cls)
                if cls and _safe_css_ident(cls):
                    groups.setdefault(f"class:{cls}", []).append(child)
        for key, items in groups.items():
            if len(items) < 3 or len(items) / len(children) < 0.4:
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
            if statistics.median(similarities) < 0.5:
                continue
            if sum(value >= 0.5 for value in similarities) / len(similarities) < 0.7:
                continue

            common_classes = set(str(v) for v in items[0].get("class", []))
            for item in items[1:]:
                common_classes.intersection_update(str(v) for v in item.get("class", []))
            common_classes = {value for value in common_classes if _safe_css_ident(value)}
            if key.startswith("class:"):
                item_part = f".{key.split(':', 1)[1]}"
            else:
                tag_name = key.split(":", 1)[1]
                item_part = tag_name + "".join(
                    f".{value}" for value in sorted(common_classes)
                )
            selector = f"{_auto_parent_selector(parent, soup)} > {item_part}"
            if selector in seen:
                continue
            try:
                matched = soup.select(selector)
            except Exception:
                continue
            if not matched or len(items) / len(matched) < 0.8 or len(matched) > 5000:
                continue
            fingerprint = tuple(id(item) for item in matched)
            if fingerprint in seen_fingerprints:
                continue
            fields, coverage = _list_fields(items)
            if len(fields) < 2 or coverage < 0.6:
                continue
            for field in fields:
                field.setdefault("selector_type", "css")
            try:
                extraction = extract_css(html, base_url, selector, fields)
            except ExtractionError:
                continue
            score = (
                0.35 * min(len(items) / 5, 1)
                + 0.25 * coverage
                + 0.2 * statistics.median(similarities)
                + 0.2 * min(len(fields) / 3, 1)
            )
            found.append(
                {
                    "kind": "list",
                    "selector": selector,
                    "item_selector": selector,
                    "item_selector_type": "css",
                    "fields": fields,
                    "headers": [field["name"] for field in fields],
                    "count": len(matched),
                    "sample": extraction.rows[:3],
                    "hidden": _is_hidden(parent),
                    "score": round(max(0.0, min(score, 1.0)), 3),
                    "rule": {
                        "mode": "css",
                        "item_selector": selector,
                        "item_selector_type": "css",
                        "fields": fields,
                    },
                }
            )
            seen.add(selector)
            seen_fingerprints.add(fingerprint)
    found.sort(key=lambda item: item["score"], reverse=True)
    return found[:limit]


# ---------------------------------------------------------------- 组合
def build_snapshot(
    html: str,
    base_url: str = "",
    *,
    reveal_hidden: bool = True,
    max_chars: int = MAX_SNAPSHOT_CHARS,
) -> dict:
    base_url = base_url or "https://example.com/"
    snapshot = sanitize_html(
        html, base_url, reveal_hidden=reveal_hidden, max_chars=max_chars
    )
    return {
        "snapshot_html": snapshot,
        "snapshot_chars": len(snapshot),
        "source_chars": len(html),
        "title": page_title(html),
        "tables": table_candidates(html),
        "lists": list_candidates(html, base_url),
    }
