"""应用配置：全部通过环境变量控制，便于本地部署与容器化。"""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .cache import HttpCache

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIE_NAME = "dh_session"
# PBKDF2 参数：迭代次数越高越安全，但登录会稍慢
PBKDF2_ITERATIONS = 260_000


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_or_create_secret(data_dir: Path) -> bytes:
    """SECRET_KEY 缺省时落盘生成，保证重启后已登录会话仍然有效。"""
    env = os.getenv("SECRET_KEY", "").strip()
    if env:
        return env.encode("utf-8")
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass
    return key


@dataclass
class Settings:
    data_dir: Path
    password_hash: str
    secret_key: bytes
    cookie_secure: bool = False
    allow_private_network: bool = False
    max_concurrent_jobs: int = 2
    session_ttl: int = 12 * 3600
    max_bytes: int = 5_000_000
    fetch_timeout: float = 25.0
    max_pages: int = 20
    max_rows: int = 50_000
    user_agent: str = (
        "DataHarvester/1.0 (self-hosted data collection tool; "
        "contact: admin@localhost)"
    )
    initial_password: str | None = None
    robot_override_allowed: bool = True
    # HTTP 缓存（TTL + ETag 条件请求）
    cache_enabled: bool = True
    cache_ttl: float = 900.0
    cache_mode: str = "enabled"
    cache_max_entries: int = 500
    cache_max_bytes: int = 50_000_000
    # 按主机限速与重试
    min_host_interval: float = 0.5
    host_jitter: float = 0.3
    max_retries: int = 2
    retry_backoff: float = 0.6
    # 浏览器渲染
    browser_block_resources: bool = True
    browser_scroll_steps: int = 6
    browser_expand_clicks: int = 5
    # 深度抓取上限
    deep_max_pages: int = 50
    cache: HttpCache | None = field(
        init=False, default=None, repr=False, compare=False
    )
    db_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "jobs.db"
        if not self.user_agent.strip():
            self.user_agent = "DataHarvester/1.0"
        mode = (self.cache_mode or "enabled").strip().lower()
        self.cache_mode = mode if mode in {"enabled", "bypass", "refresh"} else "enabled"
        if self.cache_enabled:
            self.cache = HttpCache(
                self.data_dir / "http_cache.db",
                ttl=self.cache_ttl,
                max_entries=self.cache_max_entries,
                max_bytes=self.cache_max_bytes,
            )



def _load_dotenv(path: Path) -> None:
    """极简 .env 解析，避免额外依赖。已存在的环境变量优先。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    """
    读取环境变量。密码优先级：
    1. APP_PASSWORD_HASH（推荐，PBKDF2 哈希）
    2. APP_PASSWORD（明文，仅建议本地临时使用）
    3. 都没有时自动生成随机初始密码，写入 data/initial_password.txt 并打印到控制台
    """
    from .auth import hash_password

    _load_dotenv(BASE_DIR / ".env")
    data_dir = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    password_hash = os.getenv("APP_PASSWORD_HASH", "").strip()
    initial_password = None

    if not password_hash:
        plain = os.getenv("APP_PASSWORD", "")
        if plain:
            password_hash = hash_password(plain)
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            hash_file = data_dir / "generated_password.hash"
            if hash_file.is_file():
                # 复用首次生成的密码哈希，避免每次重启都更换密码
                password_hash = hash_file.read_text(encoding="utf-8").strip()
            else:
                initial_password = secrets.token_urlsafe(9)
                password_hash = hash_password(initial_password)
                hash_file.write_text(password_hash, encoding="utf-8")
                pw_file = data_dir / "initial_password.txt"
                pw_file.write_text(
                    "DataHarvester 初始访问密码（请登录后在 .env 中设置 APP_PASSWORD 并删除本文件）\n"
                    f"{initial_password}\n",
                    encoding="utf-8",
                )
                for path in (hash_file, pw_file):
                    try:
                        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
                    except OSError:
                        pass

    return Settings(
        data_dir=data_dir,
        password_hash=password_hash,
        secret_key=_read_or_create_secret(data_dir),
        cookie_secure=_env_bool("COOKIE_SECURE", False),
        allow_private_network=_env_bool("ALLOW_PRIVATE_NETWORK", False),
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "2")),
        session_ttl=int(os.getenv("SESSION_TTL", str(12 * 3600))),
        max_bytes=int(os.getenv("MAX_BYTES", "5000000")),
        fetch_timeout=float(os.getenv("FETCH_TIMEOUT", "25")),
        max_pages=int(os.getenv("MAX_PAGES", "20")),
        max_rows=int(os.getenv("MAX_ROWS", "50000")),
        cache_enabled=_env_bool("CACHE_ENABLED", True),
        cache_ttl=float(os.getenv("CACHE_TTL", "900")),
        cache_mode=os.getenv("CACHE_MODE", "enabled"),
        cache_max_entries=int(os.getenv("CACHE_MAX_ENTRIES", "500")),
        cache_max_bytes=int(os.getenv("CACHE_MAX_BYTES", "50000000")),
        min_host_interval=float(os.getenv("HOST_MIN_INTERVAL", "0.5")),
        host_jitter=float(os.getenv("HOST_JITTER", "0.3")),
        max_retries=int(os.getenv("MAX_RETRIES", "2")),
        retry_backoff=float(os.getenv("RETRY_BACKOFF", "0.6")),
        browser_block_resources=_env_bool("BROWSER_BLOCK_RESOURCES", True),
        browser_scroll_steps=int(os.getenv("BROWSER_SCROLL_STEPS", "6")),
        browser_expand_clicks=int(os.getenv("BROWSER_EXPAND_CLICKS", "5")),
        deep_max_pages=int(os.getenv("DEEP_MAX_PAGES", "50")),
        user_agent=os.getenv("USER_AGENT", "").strip()
        or Settings.__dataclass_fields__["user_agent"].default,
        initial_password=initial_password,
    )
