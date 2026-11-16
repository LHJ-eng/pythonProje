"""任务持久化（SQLite），重启后历史记录与结果仍然可下载。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_type TEXT NOT NULL,
                url TEXT,
                mode TEXT NOT NULL,
                params TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                error TEXT,
                columns TEXT,
                rows TEXT,
                meta TEXT,
                total_rows INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)"
        )


def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "source_type": row["source_type"],
        "url": row["url"],
        "mode": row["mode"],
        "status": row["status"],
        "message": row["message"],
        "error": row["error"],
        "total_rows": row["total_rows"],
    }


def create_job(
    db_path: Path,
    *,
    job_id: str,
    source_type: str,
    url: str | None,
    mode: str,
    params: dict,
) -> dict:
    now = _now()
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO jobs (id, created_at, updated_at, source_type, url, mode,
               params, status, message, total_rows) VALUES (?,?,?,?,?,?,?,?,?,0)""",
            (
                job_id,
                now,
                now,
                source_type,
                url,
                mode,
                json.dumps(params, ensure_ascii=False),
                "queued",
                "已排队",
            ),
        )
    return get_job(db_path, job_id)  # type: ignore[return-value]


def get_job(db_path: Path, job_id: str) -> dict | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        return None
    data = _row_to_summary(row)
    data["params"] = json.loads(row["params"] or "{}")
    data["columns"] = json.loads(row["columns"] or "[]")
    data["rows"] = json.loads(row["rows"] or "[]")
    data["meta"] = json.loads(row["meta"] or "{}")
    return data


def list_jobs(db_path: Path, limit: int = 30) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        ).fetchall()
    return [_row_to_summary(row) for row in rows]


def update_job(db_path: Path, job_id: str, **fields) -> None:
    allowed = {"status", "message", "error", "columns", "rows", "meta", "total_rows"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    serialized = {}
    for key, value in updates.items():
        if key in {"columns", "rows", "meta"}:
            serialized[key] = json.dumps(value, ensure_ascii=False)
        else:
            serialized[key] = value
    serialized["updated_at"] = _now()
    assignments = ", ".join(f"{key}=?" for key in serialized)
    with _LOCK, _connect(db_path) as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id=?",
            (*serialized.values(), job_id),
        )


def delete_job(db_path: Path, job_id: str) -> bool:
    with _LOCK, _connect(db_path) as conn:
        cursor = conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    return cursor.rowcount > 0


def job_stats(db_path: Path) -> dict:
    """任务与数据量统计，供指标接口使用。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(total_rows), 0) AS rows "
            "FROM jobs GROUP BY status"
        ).fetchall()
    by_status = {row["status"]: int(row["count"]) for row in rows}
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "total_rows": sum(int(row["rows"]) for row in rows),
    }
