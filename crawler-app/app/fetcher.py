"""网页抓取引擎：httpx 静态抓取 + 可选 Playwright 浏览器渲染。"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from .config import Settings
from .security import InvalidURLError, validate_url

MAX_REDIRECTS = 5
_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset=["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)
_robots_cache: dict[str, tuple[RobotFileParser, float]] = {}
_ROBOTS_TTL = 600.0


class FetchError(RuntimeError):
    """抓取失败（网络错误、状态码异常、页面过大、被 robots 拒绝等）。"""


@dataclass
class FetchResult:
    html: str
    url: str
    status: int
    content_type: str
    elapsed_ms: int
    via: str
    truncated: bool = False


def _decode_body(body: bytes, content_type: str) -> str:
    charset = None
    match = re.search(r"charset=([a-zA-Z0-9_\-]+)", content_type or "")
    if match:
        charset = match.group(1)
    if not charset:
        meta = _META_CHARSET.search(body[:4096])
        if meta:
            charset = meta.group(1).decode("ascii", "ignore")
    for candidate in filter(None, [charset, "utf-8", "gb18030"]):
        try:
            return body.decode(candidate, errors="replace")
        except LookupError:
            continue
    return body.decode("utf-8", errors="replace")


def _client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
        timeout=httpx.Timeout(settings.fetch_timeout, connect=10.0),
        follow_redirects=False,
        trust_env=True,
    )


async def _robots_allowed(
    client: httpx.AsyncClient, url: str, settings: Settings
) -> bool:
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots_cache.get(origin)
    if cached and time.time() - cached[1] < _ROBOTS_TTL:
        return cached[0].can_fetch(settings.user_agent, url)

    parser = RobotFileParser()
    parser.set_url(f"{origin}/robots.txt")
    parser.allow_all = True
    try:
        response = await client.get(
            f"{origin}/robots.txt", timeout=min(8.0, settings.fetch_timeout)
        )
        if response.status_code == 200 and len(response.content) <= 512_000:
            parser.parse(response.text.splitlines())
        elif response.status_code in (401, 403):
            parser.disallow_all = True
    except (httpx.HTTPError, InvalidURLError):
        pass  # robots 获取失败时按允许处理（与主流爬虫一致）
    _robots_cache[origin] = (parser, time.time())
    return parser.can_fetch(settings.user_agent, url)


async def _get_with_redirects(
    client: httpx.AsyncClient, url: str, settings: Settings
) -> tuple[httpx.Response, list[str]]:
    current = url
    hops: list[str] = []
    for _ in range(MAX_REDIRECTS + 1):
        try:
            response = await client.get(current)
        except httpx.HTTPError as exc:
            raise FetchError(f"请求失败：{exc.__class__.__name__} {exc}") from exc
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise FetchError("重定向响应缺少 Location 头")
            from urllib.parse import urljoin

            current = urljoin(current, location)
            # 每一次跳转都重新做 SSRF 校验，防止跳转绕过
            current = validate_url(
                current, allow_private=settings.allow_private_network
            )
            hops.append(current)
            continue
        return response, hops
    raise FetchError("重定向次数过多")


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(
                f"响应体超过 {max_bytes // 1000} KB 限制，已中止（可用 MAX_BYTES 调整）"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_with_browser(url: str, settings: Settings) -> str:
    """同步 Playwright 调用，放在线程中执行，避免阻塞事件循环。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FetchError(
            "未安装 Playwright，无法使用浏览器渲染。"
            "请执行：pip install playwright && playwright install chromium"
        ) from exc
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=settings.user_agent)
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.fetch_timeout * 1000),
                )
                page.wait_for_timeout(1200)
                return page.content()
            finally:
                browser.close()
    except Exception as exc:  # playwright 的异常类型较杂，统一包装
        raise FetchError(f"浏览器渲染失败：{exc}") from exc


async def fetch_url(
    url: str,
    settings: Settings,
    *,
    browser: bool = False,
    ignore_robots: bool = False,
) -> FetchResult:
    started = time.perf_counter()
    url = validate_url(url, allow_private=settings.allow_private_network)

    async with _client(settings) as client:
        if not ignore_robots and not await _robots_allowed(client, url, settings):
            raise FetchError(
                "目标站点 robots.txt 禁止抓取该页面。请遵守站点规则，"
                "或确认有权抓取后勾选「忽略 robots.txt」。"
            )
        response, hops = await _get_with_redirects(client, url, settings)
        final_url = str(response.url)
        try:
            body = await _read_limited(response, settings.max_bytes)
        finally:
            await response.aclose()
        content_type = response.headers.get("content-type", "")
        status = response.status_code
        html = _decode_body(body, content_type)

    if status >= 400 and not browser:
        hint = "，该站点可能需要浏览器渲染" if status in (403, 429, 503) else ""
        raise FetchError(f"目标返回 HTTP {status}{hint}")
    if "html" not in content_type.lower() and content_type:
        raise FetchError(f"目标不是 HTML 页面（Content-Type: {content_type}）")

    via = "http"
    if browser:
        html = await asyncio.to_thread(_fetch_with_browser, final_url, settings)
        via = "browser"

    return FetchResult(
        html=html,
        url=final_url or url,
        status=status,
        content_type=content_type,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        via=via,
    )
