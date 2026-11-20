"""网页抓取引擎：httpx 静态抓取 + 可选 Playwright 浏览器渲染。"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser

import httpx

from .cache import CacheEntry
from .config import Settings
from .security import InvalidURLError, validate_url

MAX_REDIRECTS = 5
MAX_IMAGE_BYTES = 10_000_000
MAX_JSON_BYTES = 2_000_000
MAX_JSON_PAYLOADS = 20
_RETRY_STATUS = {429, 500, 502, 503, 504}
_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_FEED_CONTENT_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
}
_META_CHARSET = re.compile(
    rb"""<meta[^>]+charset=["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)
_robots_cache: dict[str, tuple[RobotFileParser, float]] = {}
_ROBOTS_TTL = 600.0
# 每个源站一把并发锁 + 下次可请求时间，避免同一主机被并发打满
_host_gates: dict[str, asyncio.Lock] = {}
_host_next_allowed: dict[str, float] = {}


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
    kind: str = "html"
    body: bytes = b""
    from_cache: bool = False
    retries: int = 0
    json_payloads: list = field(default_factory=list)


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


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


async def _throttle(url: str, settings: Settings) -> None:
    """同源站点最小请求间隔 + 随机抖动，降低被封禁概率。"""
    interval = max(0.0, float(settings.min_host_interval))
    if interval <= 0:
        return
    origin = _origin(url)
    gate = _host_gates.setdefault(origin, asyncio.Lock())
    async with gate:
        wait = _host_next_allowed.get(origin, 0.0) - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        jitter = random.uniform(0, max(0.0, float(settings.host_jitter)))
        if jitter > 0:
            await asyncio.sleep(jitter)
        _host_next_allowed[origin] = time.monotonic() + interval


def _parse_retry_after(value: str | None) -> float | None:
    """解析 Retry-After（秒数或 HTTP 日期），返回等待秒数。"""
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(raw)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    settings: Settings,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, int]:
    """GET 请求，遇到网络错误或 429/5xx 时指数退避重试，遵循 Retry-After。"""
    attempts = max(1, int(settings.max_retries) + 1)
    delay = max(0.1, float(settings.retry_backoff))
    retries = 0
    for attempt in range(attempts):
        await _throttle(url, settings)
        try:
            response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            if attempt + 1 >= attempts:
                raise FetchError(
                    f"请求失败：{exc.__class__.__name__} {exc}"
                ) from exc
            retries += 1
            await asyncio.sleep(min(delay, 10.0))
            delay = min(delay * 2, 10.0)
            continue
        if response.status_code in _RETRY_STATUS and attempt + 1 < attempts:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            await response.aclose()
            retries += 1
            await asyncio.sleep(
                min(retry_after if retry_after is not None else delay, 30.0)
            )
            delay = min(delay * 2, 10.0)
            continue
        return response, retries
    raise FetchError("请求失败：重试次数已用尽")


async def _get_with_redirects(
    client: httpx.AsyncClient,
    url: str,
    settings: Settings,
    extra_headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, list[str], int]:
    current = url
    hops: list[str] = []
    retries = 0
    for _ in range(MAX_REDIRECTS + 1):
        response, attempt_retries = await _request_with_retry(
            client,
            current,
            settings,
            extra_headers if not hops else None,
        )
        retries += attempt_retries
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise FetchError("重定向响应缺少 Location 头")
            current = urljoin(current, location)
            # 每一次跳转都重新做 SSRF 校验，防止跳转绕过
            current = validate_url(
                current, allow_private=settings.allow_private_network
            )
            hops.append(current)
            continue
        return response, hops, retries
    raise FetchError("重定向次数过多")


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(
                f"响应体超过 {max_bytes // 1000} KB 限制，已中止"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _capture_json_response(response, sink: list) -> None:
    """把 XHR / fetch 返回的 JSON 响应收集起来，供后续结构化提取使用。"""
    if len(sink) >= MAX_JSON_PAYLOADS:
        return
    try:
        request = response.request
        if request.resource_type not in {"xhr", "fetch"}:
            return
        if response.status >= 400:
            return
        content_type = (response.headers or {}).get("content-type", "")
        if "json" not in content_type.lower():
            return
        body = response.body()
        if not body or len(body) > MAX_JSON_BYTES:
            return
        import json

        payload = json.loads(body.decode("utf-8", errors="replace"))
    except Exception:
        return
    if isinstance(payload, (dict, list)):
        sink.append(payload)


def _fetch_with_browser(
    url: str,
    settings: Settings,
    *,
    wait_for: str | None = None,
    scan_full_page: bool = True,
    expand_clicks: int = 0,
) -> tuple[str, list]:
    """同步 Playwright 调用，放在线程中执行，避免阻塞事件循环。

    返回 (渲染后的 HTML, 捕获到的网络 JSON 响应列表)。
    """
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
                context = browser.new_context(
                    user_agent=settings.user_agent,
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                json_payloads: list = []
                page.on(
                    "response",
                    lambda response: _capture_json_response(response, json_payloads),
                )
                # 拦截图片 / 字体 / 媒体资源，显著加快动态页渲染
                if settings.browser_block_resources:
                    def _route(route):
                        try:
                            if route.request.resource_type in {"image", "font", "media"}:
                                route.abort()
                            else:
                                route.continue_()
                        except Exception:
                            try:
                                route.continue_()
                            except Exception:
                                pass

                    page.route("**/*", _route)
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(settings.fetch_timeout * 1000),
                )
                # 等待网络空闲（最多 3 秒），覆盖异步接口返回
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                # 等待指定选择器出现，确保目标数据已挂载
                if wait_for:
                    try:
                        page.wait_for_selector(
                            wait_for, timeout=min(int(settings.fetch_timeout * 1000), 15000)
                        )
                    except Exception:
                        pass
                page.wait_for_timeout(800)
                # 点击“展开 / 加载更多 / 查看全部”等按钮，展开被折叠的数据
                clicks = min(
                    max(0, int(expand_clicks)),
                    max(0, int(settings.browser_expand_clicks)),
                )
                if clicks > 0:
                    try:
                        page.evaluate(
                            """async (limit) => {
                                const pattern = /(展开|更多|加载更多|查看全部|显示全部|展开全部|更多内容|more|load more|view all|show all|see more)/i;
                                const nodes = Array.from(document.querySelectorAll(
                                    'button, [role="button"], a[href="#"], a[href^="javascript:"]'
                                ));
                                let clicked = 0;
                                for (const el of nodes) {
                                    if (clicked >= limit) break;
                                    const text = (
                                        el.textContent || el.getAttribute('aria-label') || ''
                                    ).trim();
                                    if (!text || text.length > 30 || !pattern.test(text)) continue;
                                    if (el.disabled) continue;
                                    try {
                                        el.addEventListener(
                                            'click', (event) => event.preventDefault(),
                                            { once: true }
                                        );
                                        el.click();
                                        clicked += 1;
                                        await new Promise((resolve) => setTimeout(resolve, 250));
                                    } catch (error) {
                                        // 单个按钮失败不影响其他按钮
                                    }
                                }
                                return clicked;
                            }""",
                            clicks,
                        )
                    except Exception:
                        pass
                    page.wait_for_timeout(400)
                # 滚动到底部触发懒加载 / 虚拟列表渲染，再回到顶部
                steps = int(settings.browser_scroll_steps) if scan_full_page else 0
                if steps > 0:
                    try:
                        page.evaluate(
                            """async (steps) => {
                                for (let i = 0; i < steps; i++) {
                                    window.scrollTo(
                                        0,
                                        document.body.scrollHeight * (i + 1) / steps
                                    );
                                    await new Promise(r => setTimeout(r, 300));
                                }
                                window.scrollTo(0, 0);
                            }""",
                            max(1, steps),
                        )
                    except Exception:
                        pass
                page.wait_for_timeout(500)
                return page.content(), json_payloads
            finally:
                browser.close()
    except FetchError:
        raise
    except Exception as exc:  # playwright 的异常类型较杂，统一包装
        raise FetchError(f"浏览器渲染失败：{exc}") from exc


def _is_supported_image(body: bytes, content_type: str) -> bool:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in _IMAGE_CONTENT_TYPES:
        return True
    return (
        body.startswith(b"\xff\xd8\xff")
        or body.startswith(b"\x89PNG\r\n\x1a\n")
        or (body.startswith(b"RIFF") and body[8:12] == b"WEBP")
    )


def _looks_like_feed(body: bytes, mime: str) -> bool:
    if mime in _FEED_CONTENT_TYPES and mime != "application/xml":
        return True
    head = body[:4096].lstrip().lower()
    if head.startswith(b"<?xml"):
        head = head.split(b"?>", 1)[-1].lstrip()
    return head.startswith(b"<rss") or head.startswith(b"<feed")


def _cache_result(entry: CacheEntry, started: float, via: str) -> FetchResult:
    mime = entry.content_type.split(";", 1)[0].strip().lower()
    kind = "feed" if _looks_like_feed(entry.body, mime) else "html"
    return FetchResult(
        html=_decode_body(entry.body, entry.content_type),
        url=entry.url,
        status=entry.status,
        content_type=entry.content_type,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        via=via,
        kind=kind,
        from_cache=True,
    )


async def fetch_url(
    url: str,
    settings: Settings,
    *,
    browser: bool = False,
    ignore_robots: bool = False,
    allow_image: bool = False,
    cache_mode: str | None = None,
    wait_for: str | None = None,
    scan_full_page: bool = True,
    expand_clicks: int = 0,
) -> FetchResult:
    started = time.perf_counter()
    url = validate_url(url, allow_private=settings.allow_private_network)
    mode = (cache_mode or settings.cache_mode or "enabled").strip().lower()
    cache = settings.cache if settings.cache_enabled and mode != "bypass" else None
    cached = cache.get(url) if cache else None

    conditional = (
        cached.validators()
        if cached and cached.status < 400 and mode in {"enabled", "refresh"}
        else None
    )

    async with _client(settings) as client:
        if not ignore_robots and not await _robots_allowed(client, url, settings):
            raise FetchError(
                "目标站点 robots.txt 禁止抓取该页面。请遵守站点规则，"
                "或确认有权抓取后勾选「忽略 robots.txt」。"
            )
        # 浏览器渲染结果依赖 JS 执行，不做 HTTP 缓存
        if cache and not browser and cached and not cached.expired:
            return _cache_result(cached, started, "cache")
        response, hops, retries = await _get_with_redirects(
            client, url, settings, extra_headers=conditional
        )
        if response.status_code == 304:
            await response.aclose()
            if cached is None:
                raise FetchError("目标返回 304，但本地没有可用缓存")
            if cache:
                cache.touch(url)
            return _cache_result(cached, started, "cache-revalidated")
        final_url = str(response.url)
        content_type = response.headers.get("content-type", "")
        status = response.status_code
        etag = response.headers.get("etag", "")
        last_modified = response.headers.get("last-modified", "")
        mime = content_type.split(";", 1)[0].strip().lower()
        max_bytes = (
            MAX_IMAGE_BYTES
            if allow_image and mime in _IMAGE_CONTENT_TYPES
            else settings.max_bytes
        )
        try:
            body = await _read_limited(response, max_bytes)
        finally:
            await response.aclose()

    kind = "html"
    if allow_image and _is_supported_image(body, content_type):
        kind = "image"
    elif allow_image and _looks_like_feed(body, mime):
        kind = "feed"
    if status >= 400 and (not browser or kind in {"image", "feed"}):
        hint = "，该站点可能需要浏览器渲染" if status in (403, 429, 503) and kind == "html" else ""
        raise FetchError(f"目标返回 HTTP {status}{hint}")
    if kind == "image":
        if len(body) > MAX_IMAGE_BYTES:
            raise FetchError("图片超过 10 MB 限制，已中止")
        html = ""
    else:
        html = _decode_body(body, content_type)
        if (
            kind == "html"
            and content_type
            and "html" not in content_type.lower()
            and "xml" not in content_type.lower()
        ):
            raise FetchError(f"目标不是 HTML 页面（Content-Type: {content_type}）")

    if cache and not browser and kind in {"html", "feed"} and status < 400:
        cache.put(
            url,
            status=status,
            content_type=content_type,
            body=body,
            etag=etag,
            last_modified=last_modified,
        )

    via = "http"
    json_payloads: list = []
    if browser and kind == "html":
        html, json_payloads = await asyncio.to_thread(
            _fetch_with_browser,
            final_url,
            settings,
            wait_for=wait_for,
            scan_full_page=scan_full_page,
            expand_clicks=expand_clicks,
        )
        via = "browser"

    return FetchResult(
        html=html,
        url=final_url or url,
        status=status,
        content_type=content_type,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        via=via,
        kind=kind,
        body=body if kind == "image" else b"",
        retries=retries,
        json_payloads=json_payloads,
    )
