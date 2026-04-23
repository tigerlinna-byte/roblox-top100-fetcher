from __future__ import annotations

import html
import json
from pathlib import Path

import requests

from .config import Config
from .roblox_creator_metrics_client import (
    BROWSER_HEADERS,
    _extract_assignment_payloads,
    _extract_json_payloads_from_script,
    _extract_metric_rank_series_from_html,
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
            headers=BROWSER_HEADERS,
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
        matched_payloads: list[dict[str, object]] = []
        for index, script_content in enumerate(_extract_script_contents(response.text)):
            decoded = html.unescape(script_content)
            lower_content = decoded.lower()
            matched_keywords = [keyword for keyword in PROBE_KEYWORDS if keyword in lower_content]
            if matched_keywords:
                matched_scripts.append(
                    {
                        "index": index,
                        "matched_keywords": matched_keywords,
                        "content_excerpt": decoded[:30000],
                    }
                )

            payloads = [
                *_extract_json_payloads_from_script(decoded),
                *_extract_assignment_payloads(decoded),
            ]
            for payload_index, payload in enumerate(payloads):
                payload_text = json.dumps(payload, ensure_ascii=False, default=str)
                matched_payload_keywords = [
                    keyword for keyword in PROBE_KEYWORDS if keyword in payload_text.lower()
                ]
                if not matched_payload_keywords:
                    continue
                matched_payloads.append(
                    {
                        "script_index": index,
                        "payload_index": payload_index,
                        "matched_keywords": matched_payload_keywords,
                        "payload_excerpt": payload_text[:30000],
                    }
                )

        summary_path = probe_dir / f"{label}_{project_id}_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "overview_url": overview_url,
                    "final_url": response.url,
                    "status_code": response.status_code,
                    "html_rank_extract_result": _extract_metric_rank_series_from_html(
                        response.text,
                        timezone_info,
                    ),
                    "matched_scripts": matched_scripts,
                    "matched_payloads": matched_payloads,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        outputs.append(str(summary_path))

    return tuple(outputs)
