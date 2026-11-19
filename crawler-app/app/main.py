"""FastAPI 应用入口：密码门禁 + 抓取 API + 导出。"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import storage
from .auth import LoginRateLimiter, issue_session, read_session, verify_password
from .config import COOKIE_NAME, Settings, load_settings
from .exporter import (
    EXPORTERS,
    column_stats,
    to_csv,
    to_html_report,
    to_json,
    to_markdown,
    to_xlsx,
)
from .extractor import (
    ExtractionError,
    analyze_page,
    build_schema,
    extract_auto,
    extract_feed,
    frame_sources,
    normalize_rule,
)
from .fetcher import FetchError, fetch_url
from .jobs import JobRequest, JobRunner, sanitize_params
from .security import InvalidURLError, validate_url
from .snapshot import build_snapshot

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class AnalyzeBody(BaseModel):
    source: Literal["url", "html"] = "url"
    url: str = Field(default="", max_length=2048)
    html: str = Field(default="", max_length=3_000_000)
    base_url: str = Field(default="", max_length=2048)
    browser: bool = False
    ignore_robots: bool = False
    wait_for: str = Field(default="", max_length=300)
    scan_full_page: bool = True
    expand_clicks: int = Field(default=0, ge=0, le=30)
    cache_mode: Literal["enabled", "bypass", "refresh"] | None = None


class SnapshotBody(BaseModel):
    source: Literal["url", "html"] = "url"
    url: str = Field(default="", max_length=2048)
    html: str = Field(default="", max_length=3_000_000)
    base_url: str = Field(default="", max_length=2048)
    browser: bool = False
    ignore_robots: bool = False
    wait_for: str = Field(default="", max_length=300)
    scan_full_page: bool = True
    expand_clicks: int = Field(default=0, ge=0, le=30)
    cache_mode: Literal["enabled", "bypass", "refresh"] | None = None
    reveal_hidden: bool = True


class TemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2048)
    rule: dict
    template_id: str | None = Field(default=None, max_length=40)


def _client_ip(request: Request) -> str:
    # 注意：如部署在反向代理后，需在代理层正确设置 X-Forwarded-For，
    # 并在这里改为只信任代理写入的头，否则限流可被伪造。
    return request.client.host if request.client else "unknown"


def _auto_payload(html: str, base_url: str) -> dict:
    """智能识别摘要 + 可复用 schema，供快照端点附带返回。"""
    try:
        extraction, detected = extract_auto(html, base_url)
        return {
            "detected": {
                **detected,
                "rows": len(extraction.rows),
                "columns": extraction.columns,
                "preview": extraction.rows[:3],
            },
            "schema": build_schema(
                extraction, detected, source_url=base_url
            ),
        }
    except ExtractionError as exc:
        return {"detected": {"mode": None, "error": str(exc)}, "schema": None}


def _session(request: Request) -> dict | None:
    settings: Settings = request.app.state.settings
    return read_session(settings.secret_key, request.cookies.get(COOKIE_NAME))


async def require_auth(request: Request) -> dict:
    session = _session(request)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return session


async def require_csrf(
    request: Request, session: dict = Depends(require_auth)
) -> dict:
    token = request.headers.get("x-csrf-token", "")
    if not token or not hmac.compare_digest(token, str(session.get("csrf", ""))):
        raise HTTPException(status_code=403, detail="CSRF 校验失败，请刷新页面重试")
    return session


def _set_security_headers(response: Response, settings: Settings) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-src 'self' blob:; "
        "frame-ancestors 'none'; form-action 'self'",
    )
    if settings.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    storage.init_db(settings.db_path)
    if settings.initial_password:
        print("=" * 64)
        print(f"DataHarvester 初始访问密码：{settings.initial_password}")
        print(f"已保存到 {settings.data_dir / 'initial_password.txt'}")
        print("请登录后在 .env 中设置 APP_PASSWORD，并删除初始密码文件。")
        print("=" * 64)

    app = FastAPI(title="DataHarvester", version="1.2.0", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.limiter = LoginRateLimiter()
    app.state.runner = JobRunner(settings)
    app.state.analyze_sem = asyncio.Semaphore(2)

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        _set_security_headers(response, settings)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def _page(name: str) -> FileResponse:
        response = FileResponse(STATIC_DIR / name, media_type="text/html")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        if not _session(request):
            return RedirectResponse("/login", status_code=302)
        return _page("index.html")

    @app.get("/login", include_in_schema=False)
    async def login_page(request: Request):
        if _session(request):
            return RedirectResponse("/", status_code=302)
        return _page("login.html")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "1.2.0"}

    @app.get("/api/metrics")
    async def metrics(session: dict = Depends(require_auth)):
        cache_stats = settings.cache.stats() if settings.cache else {"enabled": False}
        return {
            "version": "1.2.0",
            "jobs": storage.job_stats(settings.db_path),
            "cache": cache_stats,
            "settings": {
                "cache_mode": settings.cache_mode,
                "cache_ttl": settings.cache_ttl,
                "max_retries": settings.max_retries,
                "min_host_interval": settings.min_host_interval,
                "deep_max_pages": settings.deep_max_pages,
            },
        }

    @app.get("/api/me")
    async def me(request: Request):
        session = _session(request)
        return {
            "authenticated": bool(session),
            "csrf": session.get("csrf") if session else None,
        }

    @app.post("/api/login")
    async def login(request: Request, body: LoginBody):
        ip = _client_ip(request)
        limiter: LoginRateLimiter = app.state.limiter
        locked = limiter.locked_for(ip)
        if locked > 0:
            raise HTTPException(
                status_code=429,
                detail=f"尝试次数过多，请 {int(locked) + 1} 秒后再试",
            )
        if not verify_password(body.password, settings.password_hash):
            limiter.record_failure(ip)
            await asyncio.sleep(0.4)  # 轻微延时，降低爆破速度
            raise HTTPException(status_code=401, detail="密码错误")
        limiter.reset(ip)
        token, csrf = issue_session(settings.secret_key, settings.session_ttl)
        response = JSONResponse({"ok": True, "csrf": csrf})
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=settings.session_ttl,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            path="/",
        )
        return response

    @app.post("/api/logout")
    async def logout(session: dict = Depends(require_csrf)):
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.post("/api/analyze")
    async def analyze(
        request: Request,
        body: AnalyzeBody,
        session: dict = Depends(require_csrf),
    ):
        if body.source == "html":
            if len(body.html.strip()) < 20:
                raise HTTPException(status_code=400, detail="粘贴的 HTML 内容过短")
            return analyze_page(body.html, body.base_url or "https://example.com/")
        try:
            url = validate_url(
                body.url, allow_private=settings.allow_private_network
            )
        except InvalidURLError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            async with app.state.analyze_sem:
                result = await fetch_url(
                    url,
                    settings,
                    browser=body.browser,
                    ignore_robots=body.ignore_robots,
                    allow_image=True,
                    cache_mode=body.cache_mode,
                    wait_for=body.wait_for or None,
                    scan_full_page=body.scan_full_page,
                    expand_clicks=body.expand_clicks,
                )
                if result.kind == "html" and "<frameset" in result.html.lower():
                    frames = frame_sources(result.html, result.url)
                    if frames:
                        preferred = {"main", "content", "mainframe", "body"}
                        chosen = next(
                            (frame for frame in frames if frame[0].lower() in preferred),
                            frames[-1],
                        )
                        result = await fetch_url(
                            chosen[1],
                            settings,
                            browser=body.browser,
                            ignore_robots=body.ignore_robots,
                            allow_image=True,
                            cache_mode=body.cache_mode,
                            wait_for=body.wait_for or None,
                            scan_full_page=body.scan_full_page,
                            expand_clicks=body.expand_clicks,
                        )
                if result.kind == "feed":
                    extraction, rule = extract_feed(result.html, result.url)
                    return {
                        "title": "RSS / Atom 订阅源",
                        "url": result.url,
                        "tables": [],
                        "article": {"length": 0, "preview": ""},
                        "auto": {
                            **rule,
                            "rows": len(extraction.rows),
                            "columns": extraction.columns,
                            "preview": extraction.rows[:3],
                        },
                        "links": 0,
                        "chars": len(result.html),
                    }
                if result.kind == "image":
                    return {
                        "title": "图片文字识别",
                        "url": result.url,
                        "image": True,
                        "tables": [],
                        "article": {"length": 0, "preview": ""},
                        "auto": {
                            "mode": "ocr",
                            "score": 1.0,
                            "reason": "检测到图片，点击开始抓取即可识别文字",
                            "content_type": result.content_type,
                        },
                        "links": 0,
                        "chars": len(result.body),
                    }
                return analyze_page(result.html, result.url)
        except (FetchError, InvalidURLError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/snapshot")
    async def snapshot_page(
        body: SnapshotBody, session: dict = Depends(require_csrf)
    ):
        if body.source == "html":
            if len(body.html.strip()) < 20:
                raise HTTPException(status_code=400, detail="粘贴的 HTML 内容过短")
            html = body.html
            base_url = body.base_url or "https://example.com/"
            final_url, via, status, elapsed = base_url, "html", 200, 0
        else:
            try:
                url = validate_url(
                    body.url, allow_private=settings.allow_private_network
                )
            except InvalidURLError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            try:
                async with app.state.analyze_sem:
                    result = await fetch_url(
                        url,
                        settings,
                        browser=body.browser,
                        ignore_robots=body.ignore_robots,
                        allow_image=False,
                        cache_mode=body.cache_mode,
                        wait_for=body.wait_for or None,
                        scan_full_page=body.scan_full_page,
                        expand_clicks=body.expand_clicks,
                    )
            except (FetchError, InvalidURLError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if result.kind != "html":
                raise HTTPException(
                    status_code=400,
                    detail="该地址不是 HTML 页面，无法生成可视化快照",
                )
            html = result.html
            base_url = result.url
            final_url, via = result.url, result.via
            status, elapsed = result.status, result.elapsed_ms

        payload = build_snapshot(
            html, base_url, reveal_hidden=body.reveal_hidden
        )
        payload.update(_auto_payload(html, base_url))
        payload.update(
            final_url=final_url, via=via, status=status, elapsed_ms=elapsed
        )
        return payload

    @app.get("/api/templates")
    async def list_templates(session: dict = Depends(require_auth)):
        return {"templates": storage.list_templates(settings.db_path)}

    @app.post("/api/templates")
    async def save_template(
        body: TemplateBody, session: dict = Depends(require_csrf)
    ):
        try:
            rule = normalize_rule(body.rule)
        except ExtractionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not rule:
            raise HTTPException(status_code=400, detail="提取规则不能为空")
        return storage.save_template(
            settings.db_path,
            name=body.name.strip(),
            rule=rule,
            description=body.description.strip(),
            source_url=body.source_url.strip(),
            template_id=body.template_id,
        )

    @app.delete("/api/templates/{template_id}")
    async def remove_template(
        template_id: str, session: dict = Depends(require_csrf)
    ):
        if not storage.delete_template(settings.db_path, template_id):
            raise HTTPException(status_code=404, detail="模板不存在")
        return {"ok": True}

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        request: Request,
        body: JobRequest,
        session: dict = Depends(require_csrf),
    ):
        if body.source == "url":
            try:
                body.url = validate_url(
                    body.url, allow_private=settings.allow_private_network
                )
            except InvalidURLError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        recent = storage.list_jobs(settings.db_path, limit=50)
        active = sum(1 for job in recent if job["status"] in {"queued", "running"})
        if active >= 10:
            raise HTTPException(
                status_code=429, detail="排队任务过多，请等待当前任务完成"
            )
        job_id = uuid.uuid4().hex[:12]
        storage.create_job(
            settings.db_path,
            job_id=job_id,
            source_type=body.source,
            url=body.url or None,
            mode=body.mode,
            params=sanitize_params(body.model_dump()),
        )
        app.state.runner.start(job_id, body)
        return {"id": job_id, "status": "queued"}

    @app.get("/api/jobs")
    async def list_jobs(
        limit: int = 30, session: dict = Depends(require_auth)
    ):
        return {"jobs": storage.list_jobs(settings.db_path, limit=limit)}

    @app.get("/api/jobs/{job_id}")
    async def job_detail(job_id: str, session: dict = Depends(require_auth)):
        job = storage.get_job(settings.db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        preview = job["rows"][:100]
        return {
            "id": job["id"],
            "created_at": job["created_at"],
            "status": job["status"],
            "message": job["message"],
            "error": job["error"],
            "mode": job["mode"],
            "source_type": job["source_type"],
            "url": job["url"],
            "columns": job["columns"],
            "rows": preview,
            "preview_limited": len(job["rows"]) > len(preview),
            "total_rows": job["total_rows"],
            "meta": job["meta"],
            "params": job["params"],
        }

    @app.delete("/api/jobs/{job_id}")
    async def remove_job(job_id: str, session: dict = Depends(require_csrf)):
        if not storage.delete_job(settings.db_path, job_id):
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/export")
    async def export_job(
        job_id: str, format: str = "csv", session: dict = Depends(require_auth)
    ):
        fmt = format.lower()
        if fmt not in EXPORTERS:
            raise HTTPException(status_code=400, detail="不支持的导出格式")
        job = storage.get_job(settings.db_path, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] != "done":
            raise HTTPException(status_code=409, detail="任务尚未完成，无法导出")
        columns, rows, meta = job["columns"], job["rows"], job["meta"]
        media_type, extension = EXPORTERS[fmt]
        if fmt == "csv":
            payload = to_csv(columns, rows)
        elif fmt == "json":
            payload = to_json(columns, rows, meta)
        elif fmt == "xlsx":
            payload = to_xlsx(columns, rows, meta)
        elif fmt == "md":
            payload = to_markdown(columns, rows, meta)
        else:
            payload = to_html_report(
                columns, rows, meta, column_stats(columns, rows)
            )
        filename = f"dataharvester-{job_id[:8]}.{extension}"
        return Response(
            content=payload,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(404)
    async def not_found(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "接口不存在"}, status_code=404)
        return RedirectResponse("/", status_code=302)

    return app
