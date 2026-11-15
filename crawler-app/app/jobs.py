"""任务参数校验与抓取执行编排。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from . import storage
from .config import Settings
from .extractor import (
    Extraction,
    ExtractionError,
    extract_article,
    extract_css,
    extract_table,
    parse_tables,
)
from .exporter import column_stats
from .fetcher import FetchError, fetch_url
from .security import InvalidURLError, clean_text, normalize_url

MAX_HTML_CHARS = 3_000_000


class FieldSpec(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    selector: str = Field(default="", max_length=300)
    attr: str = Field(default="text", max_length=30)

    @field_validator("name", "selector", "attr")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class JobRequest(BaseModel):
    source: Literal["url", "html"] = "url"
    url: str = Field(default="", max_length=2048)
    html: str = Field(default="", max_length=MAX_HTML_CHARS)
    base_url: str = Field(default="", max_length=2048)
    mode: Literal["table", "css", "article"] = "table"
    browser: bool = False
    pages: int = Field(default=1, ge=1, le=50)
    table_index: int | None = Field(default=None, ge=0, le=999)
    first_row_header: bool = False
    item_selector: str = Field(default="", max_length=500)
    fields: list[FieldSpec] = Field(default_factory=list, max_length=30)
    ignore_robots: bool = False
    delay: float = Field(default=0.8, ge=0, le=10)

    @model_validator(mode="after")
    def _check(self) -> "JobRequest":
        if self.source == "url":
            if not self.url.strip():
                raise ValueError("请填写网页 URL")
            # 这里只做语法校验；DNS/SSRF 校验在路由层结合部署配置执行
            self.url = normalize_url(self.url)
            if self.pages > 1 and "{page}" not in self.url:
                raise ValueError("抓取多页时，URL 中需要用 {page} 作为页码占位符，例如 https://a.com/list?page={page}")
        else:
            if len(self.html.strip()) < 20:
                raise ValueError("粘贴的 HTML 内容过短")
            if self.pages > 1:
                raise ValueError("HTML 来源不支持分页抓取")
        if self.mode == "css":
            if not self.item_selector.strip():
                raise ValueError("CSS 模式需要填写条目选择器")
            if not self.fields:
                raise ValueError("CSS 模式至少需要一个字段映射")
        if self.mode == "article" and self.pages > 1:
            raise ValueError("正文模式仅支持单页")
        return self


def sanitize_params(params: dict) -> dict:
    """入库前去掉可能很大的 HTML 原文，避免数据库膨胀。"""
    stored = {k: v for k, v in params.items() if k != "html"}
    if params.get("html"):
        stored["html_chars"] = len(params["html"])
    return stored


class JobRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_jobs))
        self.tasks: set[asyncio.Task] = set()

    def start(self, job_id: str, request: JobRequest) -> None:
        task = asyncio.create_task(self._run(job_id, request))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _run(self, job_id: str, request: JobRequest) -> None:
        db = self.settings.db_path
        async with self.semaphore:
            started = time.perf_counter()
            try:
                storage.update_job(db, job_id, status="running", message="开始抓取…")
                extraction, meta = await self._execute(job_id, request)
                rows = extraction.rows[: self.settings.max_rows]
                warnings = list(extraction.warnings)
                if len(extraction.rows) > self.settings.max_rows:
                    warnings.append(
                        f"结果超过 {self.settings.max_rows} 行，仅保留前 {self.settings.max_rows} 行"
                    )
                width = len(extraction.columns)
                rows = [
                    [
                        clean_text(str(v), max_length=200_000)
                        for v in (list(row) + [""] * width)[:width]
                    ]
                    for row in rows
                ]
                meta.update(
                    {
                        "job_id": job_id,
                        "mode": request.mode,
                        "source_type": request.source,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "warnings": warnings,
                        "stats": column_stats(extraction.columns, rows),
                    }
                )
                storage.update_job(
                    db,
                    job_id,
                    status="done",
                    message="抓取完成",
                    columns=extraction.columns,
                    rows=rows,
                    meta=meta,
                    total_rows=len(rows),
                )
            except (FetchError, ExtractionError, InvalidURLError, ValueError) as exc:
                storage.update_job(
                    db, job_id, status="error", error=str(exc), message="抓取失败"
                )
            except asyncio.CancelledError:
                storage.update_job(db, job_id, status="error", error="任务已取消")
                raise
            except Exception as exc:  # 兜底，避免后台任务静默死亡
                storage.update_job(
                    db,
                    job_id,
                    status="error",
                    error=f"内部错误：{exc.__class__.__name__}: {exc}",
                )

    async def _execute(self, job_id: str, request: JobRequest) -> tuple[Extraction, dict]:
        db = self.settings.db_path
        meta: dict = {
            "source_url": request.url or request.base_url,
            "pages_requested": request.pages,
            "pages_fetched": 0,
            "via": "html",
        }
        if request.source == "html":
            html = request.html
            base = request.base_url or "https://example.com/"
            return self._extract_one(html, base, request), meta

        if request.ignore_robots and not self.settings.robot_override_allowed:
            raise ValueError("当前部署已禁用「忽略 robots.txt」选项")

        first: Extraction | None = None
        all_rows: list[list[str]] = []
        pages_fetched = 0
        warnings: list[str] = []

        for page in range(1, request.pages + 1):
            storage.update_job(
                db,
                job_id,
                message=f"正在抓取第 {page}/{request.pages} 页…",
            )
            page_url = request.url.replace("{page}", str(page))
            result = await fetch_url(
                page_url,
                self.settings,
                browser=request.browser,
                ignore_robots=request.ignore_robots,
            )
            pages_fetched += 1
            meta["final_url"] = result.url
            meta["http_status"] = result.status
            meta["via"] = result.via
            meta["fetch_ms"] = meta.get("fetch_ms", 0) + result.elapsed_ms
            try:
                extraction = self._extract_one(result.html, result.url, request, page=page)
            except ExtractionError as exc:
                if page == 1:
                    raise
                warnings.append(f"第 {page} 页解析失败，已停止翻页：{exc}")
                break
            if first is None:
                first = extraction
            all_rows.extend(extraction.rows)
            if page < request.pages and request.delay > 0:
                await asyncio.sleep(request.delay)

        assert first is not None
        meta["pages_fetched"] = pages_fetched
        first.rows = all_rows
        first.warnings.extend(warnings)
        return first, meta

    def _extract_one(
        self, html: str, base_url: str, request: JobRequest, *, page: int = 1
    ) -> Extraction:
        if request.mode == "article":
            return extract_article(html, base_url)
        if request.mode == "css":
            return extract_css(
                html,
                base_url,
                request.item_selector,
                [f.model_dump() for f in request.fields],
            )
        tables = parse_tables(html)
        extraction = extract_table(
            tables,
            table_index=request.table_index,
            first_row_header=request.first_row_header,
        )
        if page > 1:
            extraction.warnings.append("多页结果的列以第一页结构为准")
        return extraction
