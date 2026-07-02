"""Redact credentials from URLs and log/API payloads."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, urlunparse

_MYSQL_URL_RE = re.compile(
    r"(mysql(?:\+[\w]+)?://)(?:([^:@/]*)(?::([^@/]*))?@)",
    re.IGNORECASE,
)


def redact_database_url(url: str) -> str:
    """Return ``url`` with the password replaced by ``***``."""
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme.startswith("mysql"):
        return url
    if parsed.username is None and parsed.password is None:
        return url
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    if parsed.username:
        netloc = f"{parsed.username}:***@{hostname}{port}"
    else:
        netloc = f"***@{hostname}{port}"
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path or "",
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def sanitize_secrets(text: Optional[str]) -> Optional[str]:
    """Redact embedded MySQL connection strings inside arbitrary text."""
    if text is None:
        return None

    def _replace(match: re.Match[str]) -> str:
        scheme = match.group(1)
        username = match.group(2) or ""
        if username:
            return f"{scheme}{username}:***@"
        return f"{scheme}***@"

    return _MYSQL_URL_RE.sub(_replace, str(text))
