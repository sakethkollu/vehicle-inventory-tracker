"""Bootstrap Akamai/browser cookies for Mazda USA API calls."""

from __future__ import annotations

import json
import os
from typing import Dict

MAZDA_INVENTORY_URL = "https://www.mazdausa.com/shopping-tools/inventory/results"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def cookies_from_env() -> Dict[str, str]:
    raw = os.environ.get("MAZDA_SESSION_COOKIE", "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items()}
        except json.JSONDecodeError:
            pass
    cookies: Dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def fetch_mazda_cookies(
    *,
    page_url: str = MAZDA_INVENTORY_URL,
    headless: bool = True,
    wait_ms: int = 4000,
    user_agent: str = DEFAULT_USER_AGENT,
) -> Dict[str, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(wait_ms)
        cookies = {cookie["name"]: cookie["value"] for cookie in context.cookies()}
        browser.close()
        return cookies


def resolve_mazda_cookies() -> Dict[str, str]:
    cookies = cookies_from_env()
    if cookies:
        return cookies
    return fetch_mazda_cookies()
