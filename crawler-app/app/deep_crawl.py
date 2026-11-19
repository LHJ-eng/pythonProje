"""同域深度抓取（参考 crawl4ai 的 DeepCrawlStrategy）。

策略：从入口页开始做同域 BFS，可限制深度、页数，支持包含 / 排除正则，
并可选读取 /sitemap.xml 发现站点内页面。所有请求复用 fetch_url，
因此自动具备 SSRF 防护、robots.txt、限速、重试与 HTTP 缓存。
"""

from __future__ import annotations

import asyncio
import html as html_lib
import re
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

from .config import Settings
from .extractor import make_soup
from .fetcher import FetchError, FetchResult, fetch_url
from .security import InvalidURLError

# 明显不是内容页的静态资源 / 下载文件
_SKIP_EXTENSION = re.compile(
    r"\.(?:jpg|jpeg|png|gif|webp|svg|ico|bmp|tif|tiff|pdf|zip|rar|7z|gz|tar|"
    r"mp4|mp3|avi|mov|wmv|flv|exe|dmg|apk|woff2?|ttf|eot|css|js|json|xml|rss)$",
    re.IGNORECASE,
)
_SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "blob:", "#")


@dataclass
class CrawledPage:
    url: str
    depth: int
    result: FetchResult | None = None
    error: str = ""


@dataclass
class DeepCrawlResult:
    pages: list[CrawledPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    discovered: int = 0
    truncated: bool = False
    sitemap_urls: int = 0


def normalize_crawl_url(url: str) -> str:
    return urldefrag(url)[0]


def same_site(candidate: str, root: str) -> bool:
    left, right = urlsplit(candidate), urlsplit(root)
    return (left.scheme, left.netloc.lower()) == (right.scheme, right.netloc.lower())


def link_allowed(
    url: str,
    root_url: str,
    *,
    include: re.Pattern | None = None,
    exclude: re.Pattern | None = None,
) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    if not same_site(url, root_url):
        return False
    if _SKIP_EXTENSION.search(parts.path or ""):
        return False
    if exclude is not None and exclude.search(url):
        return False
    if include is not None and not include.search(url):
        return False
    return True


def compile_pattern(pattern: str) -> re.Pattern | None:
    pattern = (pattern or "").strip()
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"正则表达式无效：{exc}") from exc


def discover_links(html: str, base_url: str) -> list[str]:
    """提取页面内所有 http(s) 链接，去重并补全为绝对地址。"""
    if not html:
        return []
    soup = make_soup(html)
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all(["a", "area"], href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            continue
        url = normalize_crawl_url(urljoin(base_url, href))
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def parse_sitemap(xml_text: str, base_url: str) -> list[str]:
    """解析 sitemap / sitemap index 中的 <loc>。"""
    if not xml_text:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text, re.IGNORECASE | re.DOTALL):
        raw = html_lib.unescape(match.strip())
        if not raw:
            continue
        url = normalize_crawl_url(urljoin(base_url, raw))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


async def _sitemap_seeds(
    start_url: str, settings: Settings, *, ignore_robots: bool
) -> list[str]:
    parts = urlsplit(start_url)
    sitemap_url = f"{parts.scheme}://{parts.netloc}/sitemap.xml"
    try:
        result = await fetch_url(
            sitemap_url, settings, ignore_robots=ignore_robots, allow_image=False
        )
    except (FetchError, InvalidURLError, ValueError):
        return []
    return parse_sitemap(result.html, sitemap_url)


async def crawl_deep(
    start_url: str,
    settings: Settings,
    *,
    max_depth: int = 1,
    max_pages: int = 10,
    include: str = "",
    exclude: str = "",
    browser: bool = False,
    ignore_robots: bool = False,
    use_sitemap: bool = True,
    delay: float = 0.0,
    wait_for: str | None = None,
    scan_full_page: bool = True,
    expand_clicks: int = 0,
) -> DeepCrawlResult:
    """同域 BFS 抓取，返回按发现顺序排列的页面结果。"""
    include_re = compile_pattern(include)
    exclude_re = compile_pattern(exclude)
    limit = max(1, min(int(max_pages), max(1, int(settings.deep_max_pages))))
    depth_limit = max(0, min(int(max_depth), 5))
    result = DeepCrawlResult()
    root = normalize_crawl_url(start_url)
    queue: deque[tuple[str, int]] = deque([(root, 0)])
    seen: set[str] = {root}
    pause = max(0.0, float(delay))

    if use_sitemap and depth_limit >= 1:
        seeds = await _sitemap_seeds(root, settings, ignore_robots=ignore_robots)
        result.sitemap_urls = len(seeds)
        for seed in seeds:
            if len(seen) > limit * 8:
                result.truncated = True
                break
            if seed not in seen and link_allowed(
                seed, root, include=include_re, exclude=exclude_re
            ):
                seen.add(seed)
                queue.append((seed, 1))

    while queue and len(result.pages) < limit:
        url, depth = queue.popleft()
        try:
            page = await fetch_url(
                url,
                settings,
                browser=browser,
                ignore_robots=ignore_robots,
                allow_image=False,
                wait_for=wait_for,
                scan_full_page=scan_full_page,
                expand_clicks=expand_clicks,
            )
        except (FetchError, InvalidURLError, ValueError) as exc:
            result.errors.append(f"{url}：{exc}")
            continue
        result.pages.append(CrawledPage(url=url, depth=depth, result=page))
        if depth < depth_limit and page.kind == "html":
            for link in discover_links(page.html, page.url):
                if link in seen:
                    continue
                if not link_allowed(
                    link, root, include=include_re, exclude=exclude_re
                ):
                    continue
                if len(seen) >= limit * 8:
                    result.truncated = True
                    break
                seen.add(link)
                queue.append((link, depth + 1))
        if pause:
            await asyncio.sleep(pause)

    result.discovered = len(seen)
    if queue:
        result.truncated = True
    return result
