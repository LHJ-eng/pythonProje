"""URL 校验与 SSRF 防护。

核心原则：只允许 http/https；域名解析出的所有 IP 都必须是公网地址。
这样可阻止 file://、localhost、内网地址、云厂商元数据地址（169.254.169.254）等。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DANGEROUS_SCHEME = re.compile(
    r"^(javascript|data|file|ftp|ftps|mailto|vbscript|about|blob|chrome):", re.I
)


class InvalidURLError(ValueError):
    """URL 不合法或指向受保护地址。"""


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise InvalidURLError("URL 不能为空")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURLError("URL 过长")
    if any(ch in url for ch in ("\n", "\r", "\t", " ")):
        raise InvalidURLError("URL 中不能包含空白字符")
    if _DANGEROUS_SCHEME.match(url):
        raise InvalidURLError("仅支持 http/https 协议")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise InvalidURLError("仅支持 http/https 协议")
    if not parts.hostname:
        raise InvalidURLError("URL 缺少主机名")
    if parts.username or parts.password:
        raise InvalidURLError("URL 中不允许携带用户名/密码")
    host = parts.hostname.lower()
    if host in _BLOCKED_HOSTS or host.rstrip(".").endswith(_BLOCKED_HOST_SUFFIXES):
        raise InvalidURLError("不允许访问内网/本地主机")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidURLError("URL 端口不合法") from exc
    # 统一去掉默认端口与片段；IPv6 地址需要保留方括号
    netloc = f"[{host}]" if ":" in host else host
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """规范化 URL 并校验其解析到的所有 IP；返回规范化后的 URL。"""
    normalized = normalize_url(url)
    if allow_private:
        return normalized
    host = urlsplit(normalized).hostname
    assert host is not None
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise InvalidURLError(f"域名解析失败：{host}") from exc
    if not infos:
        raise InvalidURLError(f"域名解析失败：{host}")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise InvalidURLError("无法识别的目标地址") from None
        if _ip_is_blocked(ip):
            raise InvalidURLError(
                f"目标地址 {address} 属于内网/保留地址，已阻止（SSRF 防护）"
            )
    return normalized


def clean_text(value: str, *, max_length: int = 100_000) -> str:
    """压缩空白并移除控制字符，避免导出文件损坏。"""
    value = _CONTROL_CHARS.sub("", value or "")
    value = re.sub(r"[\s\u00a0]+", " ", value).strip()
    return value[:max_length]
