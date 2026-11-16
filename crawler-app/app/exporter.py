"""导出：CSV / Excel / JSON / 自包含 HTML 报告。"""

from __future__ import annotations

import csv
import html as html_lib
import io
import json
from datetime import datetime


def column_stats(columns: list[str], rows: list[list[str]]) -> list[dict]:
    stats = []
    for i, name in enumerate(columns):
        values = [row[i] for row in rows if i < len(row) and str(row[i]).strip()]
        stats.append(
            {
                "column": name,
                "filled": len(values),
                "distinct": len(set(values)),
                "fill_rate": round(len(values) / len(rows), 3) if rows else 0.0,
            }
        )
    return stats


def _prepare(columns: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    width = len(columns)
    normalized = [
        [str(value) if value is not None else "" for value in row][:width]
        + [""] * max(0, width - len(row))
        for row in rows
    ]
    return columns, normalized


def to_csv(columns: list[str], rows: list[list[str]]) -> bytes:
    columns, rows = _prepare(columns, rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    writer.writerows(rows)
    # utf-8-sig 让 Excel 正确识别中文
    return buffer.getvalue().encode("utf-8-sig")


def to_json(columns: list[str], rows: list[list[str]], meta: dict) -> bytes:
    columns, rows = _prepare(columns, rows)
    payload = {
        "meta": meta,
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def to_xlsx(columns: list[str], rows: list[list[str]], meta: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    columns, rows = _prepare(columns, rows)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"

    header_fill = PatternFill("solid", fgColor="1F2937")
    header_font = Font(color="FFFFFF", bold=True)
    sheet.append(columns)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row in rows:
        # Excel 单元格上限 32767 字符
        sheet.append([value[:32000] for value in row])

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(max(len(columns), 1))}{len(rows) + 1}"

    for i, name in enumerate(columns, start=1):
        width = max([len(str(name))] + [len(str(r[i - 1])) if i - 1 < len(r) else 0 for r in rows[:300]])
        sheet.column_dimensions[get_column_letter(i)].width = min(max(width + 4, 10), 60)

    info = workbook.create_sheet("任务信息")
    for key, value in (meta or {}).items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        info.append([str(key), str(value)])
    info.column_dimensions["A"].width = 22
    info.column_dimensions["B"].width = 80

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def to_markdown(columns: list[str], rows: list[list[str]], meta: dict) -> bytes:
    """Markdown 表格导出，便于直接粘贴到文档 / 笔记 / LLM 上下文。"""
    columns, rows = _prepare(columns, rows)
    source = str(meta.get("source_url") or meta.get("job_id") or "抓取结果")
    created = str(meta.get("scraped_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def cell(value: str) -> str:
        text = str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
        return text[:1000]

    lines = [
        f"# {source}",
        "",
        f"> 共 {len(rows)} 行 × {len(columns)} 列 · 生成时间 {created} · DataHarvester",
        "",
        "| " + " | ".join(cell(c) for c in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def to_html_report(
    columns: list[str], rows: list[list[str]], meta: dict, stats: list[dict]
) -> bytes:
    columns, rows = _prepare(columns, rows)
    esc = html_lib.escape
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = esc(str(meta.get("source_url") or meta.get("job_id") or "数据报告"))

    stat_rows = "".join(
        f"<tr><td>{esc(str(s['column']))}</td><td>{s['filled']}</td>"
        f"<td>{s['distinct']}</td>"
        f"<td><div class='bar'><span style='width:{int(s['fill_rate'] * 100)}%'></span></div>"
        f"<em>{int(s['fill_rate'] * 100)}%</em></td></tr>"
        for s in stats
    )
    head = "".join(f"<th>{esc(str(c))}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(str(v))}</td>" for v in row) + "</tr>" for row in rows
    )
    meta_rows = "".join(
        f"<li><b>{esc(str(k))}</b>：{esc(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))}</li>"
        for k, v in (meta or {}).items()
    )

    document = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · 数据报告</title>
<style>
:root{{--bg:#0f172a;--card:#151f35;--line:#26344d;--text:#e6edf7;--muted:#93a4bf;--accent:#38bdf8}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;padding:32px}}
h1{{font-size:22px;margin:0 0 4px}} .sub{{color:var(--muted);font-size:12px;margin-bottom:24px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin-bottom:20px;overflow:auto}}
.badge{{display:inline-block;background:rgba(56,189,248,.12);color:var(--accent);border:1px solid rgba(56,189,248,.35);padding:2px 10px;border-radius:999px;font-size:12px;margin-right:8px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top;max-width:420px;word-break:break-word}}
th{{position:sticky;top:0;background:#1b2740;color:#cfe3ff;font-weight:600}}
tr:hover td{{background:rgba(56,189,248,.05)}}
.bar{{display:inline-block;width:120px;height:8px;background:#22304a;border-radius:99px;overflow:hidden;vertical-align:middle}}
.bar span{{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#22d3ee)}}
em{{color:var(--muted);font-style:normal;margin-left:8px;font-size:12px}}
ul{{padding-left:18px;color:var(--muted);font-size:12px}} b{{color:var(--text);font-weight:500}}
</style></head><body>
<h1>{title}</h1>
<div class="sub">生成时间 {created} · 共 {len(rows)} 行 × {len(columns)} 列 · DataHarvester</div>
<div class="card"><span class="badge">字段完整度</span>
<table><thead><tr><th>字段</th><th>非空数</th><th>去重值</th><th>填充率</th></tr></thead>
<tbody>{stat_rows}</tbody></table></div>
<div class="card"><span class="badge">任务信息</span><ul>{meta_rows}</ul></div>
<div class="card"><span class="badge">数据明细</span>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
</body></html>"""
    return document.encode("utf-8")


EXPORTERS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "json": ("application/json; charset=utf-8", "json"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx",
    ),
    "html": ("text/html; charset=utf-8", "html"),
    "md": ("text/markdown; charset=utf-8", "md"),
}
