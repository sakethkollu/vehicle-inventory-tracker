"""Fetch a Toyota AWS WAF token using a real browser session."""

from __future__ import annotations

DEFAULT_PAGE_URL = "https://www.toyota.com/search-inventory/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)


def _cookie_token(cookies: list[dict]) -> str | None:
    for cookie in cookies:
        if cookie.get("name") == "aws-waf-token" and cookie.get("value"):
            return cookie["value"]
    return None


def fetch_waf_token(
    page_url: str = DEFAULT_PAGE_URL,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()

        page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(2000)

        token = _cookie_token(context.cookies())
        if not token:
            token = page.evaluate(
                """async () => {
                    const integration = window.AwsWafIntegration;
                    if (integration?.getToken) {
                        return await integration.getToken();
                    }
                    if (integration?.hasToken?.()) {
                        const cookies = document.cookie.split('; ');
                        for (const entry of cookies) {
                            if (entry.startsWith('aws-waf-token=')) {
                                return entry.slice('aws-waf-token='.length);
                            }
                        }
                    }
                    return null;
                }"""
            )

        if not token:
            deadline_ms = timeout_ms
            poll_ms = 500
            elapsed_ms = 2000
            while elapsed_ms < deadline_ms:
                page.wait_for_timeout(poll_ms)
                elapsed_ms += poll_ms
                token = _cookie_token(context.cookies())
                if token:
                    break
                token = page.evaluate(
                    """async () => {
                        const integration = window.AwsWafIntegration;
                        if (integration?.getToken) {
                            return await integration.getToken();
                        }
                        return null;
                    }"""
                )
                if token:
                    break

        browser.close()

    if not token:
        raise RuntimeError(
            "Could not obtain aws-waf-token from Playwright session. "
            f"Loaded {page_url!r} but WAF integration never produced a token."
        )
    return token
