from __future__ import annotations

import json

from app.exporter import column_stats, to_csv, to_html_report, to_json, to_xlsx

COLUMNS = ["名称", "价格"]
ROWS = [["苹果", "5.5"], ["香蕉", "3.2"]]


def test_csv_has_excel_friendly_bom():
    payload = to_csv(COLUMNS, ROWS)
    assert payload.startswith(b"\xef\xbb\xbf")
    text = payload.decode("utf-8-sig")
    assert "名称,价格" in text


def test_json_contains_rows_as_objects():
    data = json.loads(to_json(COLUMNS, ROWS, {"job_id": "abc"}).decode("utf-8"))
    assert data["meta"]["job_id"] == "abc"
    assert data["rows"][0] == {"名称": "苹果", "价格": "5.5"}


def test_xlsx_is_valid_zip_package():
    payload = to_xlsx(COLUMNS, ROWS, {"job_id": "abc"})
    assert payload[:2] == b"PK"
    assert len(payload) > 1000


def test_html_report_escapes_content_and_has_stats():
    stats = column_stats(COLUMNS, ROWS)
    payload = to_html_report(COLUMNS, [["<script>", "1"]], {}, stats)
    text = payload.decode("utf-8")
    assert "&lt;script&gt;" in text
    assert "字段完整度" in text


def test_column_stats_counts_filled_and_distinct():
    stats = column_stats(["a", "b"], [["x", ""], ["x", "y"], ["", "y"]])
    assert stats[0] == {
        "column": "a",
        "filled": 2,
        "distinct": 1,
        "fill_rate": 0.667,
    }
