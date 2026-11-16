"""HTTP 响应缓存（SQLite，参考 crawl4ai 的 cache_mode 设计）。

能力：
- TTL 内的命中直接复用响应，减少重复抓取与目标站点压力；
- 缓存过期后携带 ETag / Last-Modified 发送条件请求，命中 304 时复用本地响应体；
- 容量上限与过期清理，避免缓存库无限增长；
- 线程安全，可被 FastAPI 后台任务并发使用。
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

CACHE_MODES = ("enabled", "bypass", "refresh")


@dataclass
class CacheEntry:
    url: str
    status: int
    content_type: str
    body: bytes
    etag: str
    last_modified: str
    created_at: float
    expires_at: float

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def validators(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers


class HttpCache:
    """SQLite 持久化 HTTP 缓存。"""

    def __init__(
        self,
        path: Path,
        *,
        ttl: float = 900.0,
        max_entries: int = 500,
        max_bytes: int = 50_000_000,
    ) -> None:
        self.path = Path(path)
        self.ttl = max(0.0, float(ttl))
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1024, int(max_bytes))
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.revalidated = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    # -------------------------------------------------------------- 内部
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS http_cache (
                    url_key TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    body BLOB NOT NULL,
                    etag TEXT NOT NULL DEFAULT '',
                    last_modified TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    size INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_http_cache_created "
                "ON http_cache(created_at)"
            )

    @staticmethod
    def key_for(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8", "ignore")).hexdigest()

    def _evict(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM http_cache WHERE expires_at < ?", (time.time() - 86400,))
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS total FROM http_cache"
        ).fetchone()
        count, total = int(row["count"]), int(row["total"])
        if count <= self.max_entries and total <= self.max_bytes:
            return
        # 从最旧的开始删除，直到同时满足条数与字节上限
        cursor = conn.execute(
            "SELECT url_key, size FROM http_cache ORDER BY created_at ASC"
        )
        for item in cursor.fetchall():
            if count <= self.max_entries and total <= self.max_bytes:
                break
            conn.execute("DELETE FROM http_cache WHERE url_key=?", (item["url_key"],))
            count -= 1
            total -= int(item["size"])

    # -------------------------------------------------------------- 公共
    def get(self, url: str) -> CacheEntry | None:
        key = self.key_for(url)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM http_cache WHERE url_key=?", (key,)
            ).fetchone()
        if row is None:
            self.misses += 1
            return None
        self.hits += 1
        return CacheEntry(
            url=row["url"],
            status=int(row["status"]),
            content_type=row["content_type"],
            body=bytes(row["body"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
        )

    def put(
        self,
        url: str,
        *,
        status: int,
        content_type: str,
        body: bytes,
        etag: str = "",
        last_modified: str = "",
        ttl: float | None = None,
    ) -> None:
        now = time.time()
        expires = now + (self.ttl if ttl is None else max(0.0, ttl))
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO http_cache
                    (url_key, url, status, content_type, body, etag,
                     last_modified, created_at, expires_at, size)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url_key) DO UPDATE SET
                    status=excluded.status,
                    content_type=excluded.content_type,
                    body=excluded.body,
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    created_at=excluded.created_at,
                    expires_at=excluded.expires_at,
                    size=excluded.size
                """,
                (
                    self.key_for(url),
                    url,
                    int(status),
                    content_type or "",
                    body,
                    etag or "",
                    last_modified or "",
                    now,
                    expires,
                    len(body),
                ),
            )
            self._evict(conn)

    def touch(self, url: str, *, ttl: float | None = None) -> None:
        """304 命中后延长有效期，继续使用本地响应体。"""
        now = time.time()
        expires = now + (self.ttl if ttl is None else max(0.0, ttl))
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE http_cache SET expires_at=?, created_at=? WHERE url_key=?",
                (expires, now, self.key_for(url)),
            )
        self.revalidated += 1

    def delete(self, url: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM http_cache WHERE url_key=?", (self.key_for(url),))

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM http_cache")

    def stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count, COALESCE(SUM(size), 0) AS total "
                "FROM http_cache"
            ).fetchone()
        return {
            "enabled": True,
            "entries": int(row["count"]),
            "bytes": int(row["total"]),
            "ttl_seconds": self.ttl,
            "hits": self.hits,
            "misses": self.misses,
            "revalidated": self.revalidated,
        }
