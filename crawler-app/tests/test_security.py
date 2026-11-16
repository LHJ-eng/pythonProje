from __future__ import annotations

import pytest

from app.security import InvalidURLError, clean_text, normalize_url, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/data",
        "javascript:alert(1)",
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://user:pass@example.com/",
        "http://[::1]/",
    ],
)
def test_blocks_unsafe_urls(url):
    with pytest.raises(InvalidURLError):
        validate_url(url)


def test_allows_public_domain():
    assert validate_url("https://1.1.1.1/a?b=1") == "https://1.1.1.1/a?b=1"


def test_private_allowed_only_with_flag():
    assert validate_url("http://127.0.0.1:8000/", allow_private=True).startswith(
        "http://127.0.0.1:8000/"
    )


def test_scheme_defaults_to_https():
    assert normalize_url("example.com/path") == "https://example.com/path"


def test_fragment_and_default_port_removed():
    assert normalize_url("https://example.com:443/x#frag") == "https://example.com/x"


def test_clean_text_collapses_and_removes_control_chars():
    assert clean_text("  a\x00b\n\t c  ") == "ab c"
