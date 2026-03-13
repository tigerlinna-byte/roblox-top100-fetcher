from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Response, async_playwright


TARGET_KEYWORDS = (
    "analytics",
    "metrics",
    "retention",
    "engagement",
    "acquisition",
    "monetization",
    "recommendation",
    "recommendations",
    "ccu",
    "dashboard",
)
MAX_BODY_LENGTH = 20_000
OUTPUT_DIR = Path("data")
NETWORK_DEBUG_PATH = OUTPUT_DIR / "creator_metrics_network_debug.json"
CANDIDATE_ENDPOINTS_PATH = OUTPUT_DIR / "creator_metrics_candidate_endpoints.json"
DEFAULT_URL = "https://create.roblox.com/dashboard/creations/experiences/9682356542/overview"
DEFAULT_WAIT_MS = 15_000


@dataclass(frozen=True)
class CapturedResponse:
    """表示一次被捕获的页面网络响应。"""

    url: str
    method: str
    status: int
    resource_type: str
    matched_keywords: tuple[str, ...]
    request_headers: dict[str, str]
    request_body_excerpt: str
    response_headers: dict[str, str]
    body_excerpt: str


async def main() -> None:
    """启动 Playwright，打开 Creator overview 页面并捕获请求。"""

    overview_url = os.getenv("ROBLOX_CREATOR_OVERVIEW_URL", DEFAULT_URL).strip() or DEFAULT_URL
    roblox_cookie = os.getenv("ROBLOX_CREATOR_COOKIE", "").strip()
    if not roblox_cookie:
        raise RuntimeError("ROBLOX_CREATOR_COOKIE 未配置")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    captured: list[CapturedResponse] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _install_cookie(context, roblox_cookie)
        page = await context.new_page()
        page.on("response", lambda response: _schedule_capture(page, response, captured))

        await page.goto(overview_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(DEFAULT_WAIT_MS)
        await _perform_light_interactions(page)
        await page.wait_for_timeout(DEFAULT_WAIT_MS)

        await context.close()
        await browser.close()

    payload = {
        "overview_url": overview_url,
        "captured_count": len(captured),
        "responses": [asdict(item) for item in captured],
    }
    NETWORK_DEBUG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    candidates = _build_candidate_summary(captured)
    CANDIDATE_ENDPOINTS_PATH.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Captured {len(captured)} candidate responses")
    print(f"Network debug written to {NETWORK_DEBUG_PATH}")
    print(f"Candidate summary written to {CANDIDATE_ENDPOINTS_PATH}")


async def _install_cookie(context: BrowserContext, roblox_cookie: str) -> None:
    """向浏览器上下文注入 Roblox 登录态。"""

    await context.add_cookies(
        [
            {
                "name": ".ROBLOSECURITY",
                "value": roblox_cookie,
                "domain": ".roblox.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": ".ROBLOSECURITY",
                "value": roblox_cookie,
                "domain": ".create.roblox.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
        ]
    )


async def _perform_light_interactions(page: Page) -> None:
    """做少量页面交互，促使懒加载请求发出。"""

    await page.mouse.wheel(0, 1200)
    await page.wait_for_timeout(2000)
    await page.mouse.wheel(0, -800)
    await page.wait_for_timeout(1000)


def _schedule_capture(page: Page, response: Response, captured: list[CapturedResponse]) -> None:
    """异步捕获满足关键字条件的网络响应。"""

    url = response.url.lower()
    matched_keywords = tuple(keyword for keyword in TARGET_KEYWORDS if keyword in url)
    if not matched_keywords:
        return
    asyncio.create_task(_capture_response(page, response, matched_keywords, captured))


async def _capture_response(
    page: Page,
    response: Response,
    matched_keywords: tuple[str, ...],
    captured: list[CapturedResponse],
) -> None:
    """读取响应内容并保留关键摘要。"""

    del page
    request = response.request
    try:
        body_text = await response.text()
    except Exception as exc:  # noqa: BLE001
        body_text = f"<body unreadable: {exc}>"
    request_body = request.post_data or ""

    captured.append(
        CapturedResponse(
            url=response.url,
            method=request.method,
            status=response.status,
            resource_type=request.resource_type,
            matched_keywords=matched_keywords,
            request_headers=_filter_headers(await request.all_headers()),
            request_body_excerpt=request_body[:MAX_BODY_LENGTH],
            response_headers=_filter_headers(await response.all_headers()),
            body_excerpt=body_text[:MAX_BODY_LENGTH],
        )
    )


def _filter_headers(headers: dict[str, str]) -> dict[str, str]:
    """只保留侦察需要的关键请求头，避免输出噪音过大。"""

    keep = {
        "accept",
        "content-type",
        "origin",
        "referer",
        "x-csrf-token",
        "x-requested-with",
    }
    return {key: value for key, value in headers.items() if key.lower() in keep}


def _build_candidate_summary(captured: list[CapturedResponse]) -> list[dict[str, Any]]:
    """压缩输出最值得继续分析的候选接口。"""

    summary: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in captured:
        if item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        summary.append(
            {
                "url": item.url,
                "method": item.method,
                "status": item.status,
                "resource_type": item.resource_type,
                "matched_keywords": list(item.matched_keywords),
                "request_body_excerpt": item.request_body_excerpt[:2000],
                "body_excerpt": item.body_excerpt[:2000],
            }
        )
    return summary


if __name__ == "__main__":
    asyncio.run(main())
