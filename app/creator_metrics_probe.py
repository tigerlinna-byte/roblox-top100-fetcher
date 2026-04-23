from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import Config
from .roblox_creator_metrics_client import (
    ANALYTICS_BENCHMARK_SCORECARD_URL_TEMPLATE,
    ANALYTICS_HEADERS,
    BENCHMARK_SCORECARD_SPECS,
    _extract_project_id,
    _extract_script_contents,
    _resolve_business_timezone,
)


PROBE_KEYWORDS = (
    "percentile",
    "benchmark",
    "peer",
    "retention",
    "payer",
    "arppu",
    "session",
    "duration",
)
PROBE_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
}


def run_creator_metrics_probe(cfg: Config) -> tuple[str, ...]:
    """抓取 Creator overview 真实页面并输出调试材料。"""

    probe_dir = Path(cfg.output_dir) / "creator_metrics_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[str] = []
    timezone_info = _resolve_business_timezone(cfg.feishu_timezone)
    for label, overview_url in (
        ("primary", cfg.roblox_creator_overview_url.strip()),
        ("secondary", cfg.roblox_creator_overview_url_2.strip()),
    ):
        if not overview_url:
            continue
        response = requests.get(
            overview_url,
            headers=PROBE_PAGE_HEADERS,
            cookies={".ROBLOSECURITY": cfg.roblox_creator_cookie},
            timeout=cfg.request_timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()

        project_id = _extract_project_id(overview_url) or label
        html_path = probe_dir / f"{label}_{project_id}_overview.html"
        html_path.write_text(response.text, encoding="utf-8")
        outputs.append(str(html_path))

        matched_scripts: list[dict[str, object]] = []
        for index, script_content in enumerate(_extract_script_contents(response.text)):
            lower_content = script_content.lower()
            matched_keywords = [keyword for keyword in PROBE_KEYWORDS if keyword in lower_content]
            if matched_keywords:
                matched_scripts.append(
                    {
                        "index": index,
                        "matched_keywords": matched_keywords,
                        "content_excerpt": script_content[:30000],
                    }
                )

        benchmark_scorecards: dict[str, object] = {}
        for spec in BENCHMARK_SCORECARD_SPECS:
            scorecard_url = ANALYTICS_BENCHMARK_SCORECARD_URL_TEMPLATE.format(
                resource_id=project_id,
                metric=spec.metric,
            )
            scorecard_response = requests.get(
                scorecard_url,
                headers=ANALYTICS_HEADERS,
                cookies={".ROBLOSECURITY": cfg.roblox_creator_cookie},
                timeout=cfg.request_timeout_seconds,
                allow_redirects=True,
            )
            scorecard_response.raise_for_status()
            benchmark_scorecards[spec.metric] = scorecard_response.json()

        summary_path = probe_dir / f"{label}_{project_id}_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "overview_url": overview_url,
                    "final_url": response.url,
                    "status_code": response.status_code,
                    "timezone": str(timezone_info),
                    "matched_scripts": matched_scripts,
                    "benchmark_scorecards": benchmark_scorecards,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        outputs.append(str(summary_path))

    return tuple(outputs)
