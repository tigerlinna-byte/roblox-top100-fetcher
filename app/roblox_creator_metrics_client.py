from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from .config import Config
from .project_metrics_models import ProjectDailyMetricsRecord, now_iso
from .retry import with_retry


class RobloxCreatorMetricsClientError(RuntimeError):
    """表示 Roblox Creator 后台指标抓取失败。"""


@dataclass(frozen=True)
class MetricDefinition:
    """描述一个指标字段的别名集合。"""

    field_name: str
    aliases: tuple[str, ...]


METRIC_DEFINITIONS = (
    MetricDefinition("average_ccu", ("average ccu", "avg ccu")),
    MetricDefinition("peak_ccu", ("peak ccu", "peak concurrent users", "peak concurrents")),
    MetricDefinition(
        "average_session_time",
        ("average session time", "avg session time", "average play time", "average session length"),
    ),
    MetricDefinition("day1_retention", ("day 1 retention", "d1 retention", "1 day retention")),
    MetricDefinition("day7_retention", ("day 7 retention", "d7 retention", "7 day retention")),
    MetricDefinition(
        "payer_conversion_rate",
        ("payer conversion rate", "payer conversion", "payment conversion rate", "pay rate"),
    ),
    MetricDefinition("arppu", ("arppu", "average revenue per paying user")),
    MetricDefinition("qptr", ("qptr", "qtpr")),
    MetricDefinition(
        "five_minute_retention",
        ("5 minute retention", "5-minute retention", "five minute retention"),
    ),
    MetricDefinition(
        "home_recommendations",
        (
            "home recommendations",
            "home recommendation",
            "home recommendation impressions",
            "home recommendation count",
        ),
    ),
)
VALUE_CANDIDATE_KEYS = (
    "value",
    "displayValue",
    "formattedValue",
    "formatted_value",
    "display_value",
    "metricValue",
    "metric_value",
    "currentValue",
    "current_value",
)
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
}
INLINE_JSON_PATTERN = re.compile(r"<script[^>]*>(?P<content>.*?)</script>", re.IGNORECASE | re.DOTALL)
JSON_PARSE_PATTERN = re.compile(r"JSON\.parse\((?P<quoted>\"(?:\\.|[^\"])*\")\)", re.DOTALL)
VALUE_PATTERN = re.compile(
    r"(?P<value>(?:\$|USD\s*)?\d[\d,]*(?:\.\d+)?%?|\d+h\s*\d+m(?:\s*\d+s)?|\d+m\s*\d+s|\d+[:]\d+|\d+)",
    re.IGNORECASE,
)
DEBUG_HTML_MAX_LENGTH = 120_000
DEBUG_TEXT_MAX_LENGTH = 20_000


class _VisibleTextParser(HTMLParser):
    """提取页面中的可见文本，跳过脚本与样式内容。"""

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[str] = []
        self._ignored_depth = 0

    @property
    def segments(self) -> list[str]:
        return self._segments

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth > 0:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        normalized = _normalize_space(data)
        if normalized:
            self._segments.append(normalized)


@dataclass
class RobloxCreatorMetricsClient:
    """负责抓取 Roblox Creator 后台项目 overview 指标。"""

    config: Config
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def fetch_project_daily_metrics(self) -> ProjectDailyMetricsRecord:
        """抓取项目 overview 页面，并提取日报所需指标。"""

        overview_url = self.config.roblox_creator_overview_url.strip()
        if not overview_url:
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_OVERVIEW_URL 未配置")
        if not self.config.roblox_creator_cookie.strip():
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_COOKIE 未配置")

        html_text = self._fetch_overview_html(overview_url)
        project_id = _extract_project_id(overview_url)
        metrics = self._extract_metrics(html_text)
        missing_fields = [
            definition.field_name
            for definition in METRIC_DEFINITIONS
            if definition.field_name not in metrics
        ]
        if missing_fields:
            debug_path = self._write_debug_snapshot(html_text, metrics, missing_fields)
            raise RobloxCreatorMetricsClientError(
                "Creator overview 页面缺少指标: "
                + ", ".join(missing_fields)
                + f"；已输出调试样本: {debug_path}"
            )

        report_date = _resolve_report_date(self.config.feishu_timezone)
        return ProjectDailyMetricsRecord(
            report_date=report_date,
            average_ccu=metrics["average_ccu"],
            peak_ccu=metrics["peak_ccu"],
            average_session_time=metrics["average_session_time"],
            day1_retention=metrics["day1_retention"],
            day7_retention=metrics["day7_retention"],
            payer_conversion_rate=metrics["payer_conversion_rate"],
            arppu=metrics["arppu"],
            qptr=metrics["qptr"],
            five_minute_retention=metrics["five_minute_retention"],
            home_recommendations=metrics["home_recommendations"],
            project_id=project_id,
            source_url=overview_url,
            fetched_at=now_iso(),
        )

    def _fetch_overview_html(self, overview_url: str) -> str:
        def _call() -> str:
            assert self.session is not None
            response = self.session.request(
                method="GET",
                url=overview_url,
                headers=BROWSER_HEADERS,
                cookies={".ROBLOSECURITY": self.config.roblox_creator_cookie},
                timeout=self.config.request_timeout_seconds,
                allow_redirects=True,
            )
            if response.status_code >= 400:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}: {response.text[:400]}",
                    response=response,
                )
            if "login" in response.url.lower():
                raise RobloxCreatorMetricsClientError("Creator 后台请求被重定向到登录页，请检查 Cookie 是否有效")
            return response.text

        try:
            return with_retry(
                _call,
                attempts=self.config.retry_max_attempts,
                base_backoff_seconds=self.config.retry_backoff_seconds,
                is_retryable=_is_retryable_exception,
            )
        except RobloxCreatorMetricsClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RobloxCreatorMetricsClientError(f"请求 Creator overview 失败: {overview_url}") from exc

    def _extract_metrics(self, html_text: str) -> dict[str, str]:
        metrics: dict[str, str] = {}
        metrics.update(self._extract_metrics_from_inline_json(html_text))
        metrics.update(self._extract_metrics_from_script_assignments(html_text))
        visible_metrics = self._extract_metrics_from_visible_text(html_text)
        for key, value in visible_metrics.items():
            metrics.setdefault(key, value)
        return metrics

    def _extract_metrics_from_inline_json(self, html_text: str) -> dict[str, str]:
        metrics: dict[str, str] = {}
        for script_content in _extract_script_contents(html_text):
            stripped = html.unescape(script_content).strip()
            if not stripped:
                continue
            for payload in _extract_json_payloads_from_script(stripped):
                self._collect_metrics_from_payload(payload, metrics)
        return metrics

    def _extract_metrics_from_script_assignments(self, html_text: str) -> dict[str, str]:
        metrics: dict[str, str] = {}
        for script_content in _extract_script_contents(html_text):
            decoded = html.unescape(script_content)
            if not decoded:
                continue
            for payload in _extract_assignment_payloads(decoded):
                self._collect_metrics_from_payload(payload, metrics)
        return metrics

    def _collect_metrics_from_payload(self, payload, metrics: dict[str, str]) -> None:
        if isinstance(payload, dict):
            label_fields = ["label", "name", "title", "metric", "heading", "header", "metricName"]
            for field in label_fields:
                raw_label = payload.get(field)
                if not isinstance(raw_label, str):
                    continue
                matched_field = _match_metric_alias(raw_label)
                if not matched_field:
                    continue
                value = _extract_value_from_payload(payload)
                if value:
                    metrics.setdefault(matched_field, value)

            for key, value in payload.items():
                matched_field = _match_metric_alias(str(key))
                if matched_field and _is_scalar_metric_value(value):
                    metrics.setdefault(matched_field, _normalize_metric_value(str(value)))
                self._collect_metrics_from_payload(value, metrics)
            return

        if isinstance(payload, list):
            for item in payload:
                self._collect_metrics_from_payload(item, metrics)

    def _extract_metrics_from_visible_text(self, html_text: str) -> dict[str, str]:
        parser = _VisibleTextParser()
        parser.feed(html_text)
        segments = parser.segments
        metrics: dict[str, str] = {}
        lower_segments = [_normalize_label(segment) for segment in segments]
        for index, normalized_segment in enumerate(lower_segments):
            matched_field = _match_metric_alias(normalized_segment)
            if not matched_field:
                continue
            candidate_values = []
            same_segment_value = _extract_inline_value(segments[index], normalized_segment)
            if same_segment_value:
                candidate_values.append(same_segment_value)
            for offset in range(1, 6):
                if index + offset >= len(segments):
                    break
                next_segment = segments[index + offset]
                if _match_metric_alias(lower_segments[index + offset]):
                    break
                extracted = _extract_metric_value(next_segment)
                if extracted:
                    candidate_values.append(extracted)
                    break
            if candidate_values:
                metrics.setdefault(matched_field, candidate_values[0])
        return metrics

    def _write_debug_snapshot(
        self,
        html_text: str,
        metrics: dict[str, str],
        missing_fields: list[str],
    ) -> str:
        target_dir = Path(self.config.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        debug_path = target_dir / "creator_overview_debug.json"
        parser = _VisibleTextParser()
        parser.feed(html_text)
        payload = {
            "captured_metrics": metrics,
            "missing_fields": missing_fields,
            "html_excerpt": html_text[:DEBUG_HTML_MAX_LENGTH],
            "visible_text_excerpt": parser.segments[:200],
            "script_excerpt": _extract_script_contents(html_text)[:10],
        }
        debug_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logging.warning("Creator overview debug snapshot saved to %s", debug_path)
        return str(debug_path)


def _extract_project_id(overview_url: str) -> str:
    match = re.search(r"/experiences/(\d+)/overview", overview_url)
    if not match:
        return ""
    return match.group(1)


def _extract_script_contents(html_text: str) -> list[str]:
    return [match.group("content") for match in INLINE_JSON_PATTERN.finditer(html_text)]


def _extract_json_payloads_from_script(script_content: str) -> list[object]:
    payloads: list[object] = []
    stripped = script_content.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        payload = _try_load_json(stripped)
        if payload is not None:
            payloads.append(payload)
    for match in JSON_PARSE_PATTERN.finditer(script_content):
        try:
            decoded = json.loads(match.group("quoted"))
        except json.JSONDecodeError:
            continue
        payload = _try_load_json(decoded)
        if payload is not None:
            payloads.append(payload)
    return payloads


def _extract_assignment_payloads(script_content: str) -> list[object]:
    payloads: list[object] = []
    for token in ("=", ":"):
        search_from = 0
        while True:
            position = script_content.find(token, search_from)
            if position < 0:
                break
            start_index = _find_json_start(script_content, position + 1)
            if start_index < 0:
                search_from = position + 1
                continue
            candidate = _extract_balanced_json(script_content, start_index)
            if candidate:
                payload = _try_load_json(candidate)
                if payload is not None:
                    payloads.append(payload)
            search_from = position + 1
    return payloads


def _find_json_start(text: str, start_index: int) -> int:
    for index in range(start_index, len(text)):
        if text[index] in "[{":
            return index
        if not text[index].isspace():
            return -1
    return -1


def _extract_balanced_json(text: str, start_index: int) -> str:
    opening = text[start_index]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == opening:
            depth += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    return ""


def _try_load_json(candidate: str) -> object | None:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _match_metric_alias(raw_label: str) -> str:
    normalized = _normalize_label(raw_label)
    for definition in METRIC_DEFINITIONS:
        if normalized in definition.aliases:
            return definition.field_name
    return ""


def _normalize_label(value: str) -> str:
    return _normalize_space(value).lower().replace("_", " ")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_inline_value(segment: str, normalized_label: str) -> str:
    original_lower = _normalize_label(segment)
    if original_lower == normalized_label:
        return ""
    suffix = original_lower.replace(normalized_label, "", 1).strip(" :-")
    if not suffix:
        return ""
    return _extract_metric_value(suffix)


def _extract_value_from_payload(payload: dict) -> str:
    for key in VALUE_CANDIDATE_KEYS:
        raw_value = payload.get(key)
        if _is_scalar_metric_value(raw_value):
            return _normalize_metric_value(str(raw_value))
    for key, raw_value in payload.items():
        if key in {"label", "name", "title", "metric", "heading", "header", "metricName"}:
            continue
        if _is_scalar_metric_value(raw_value):
            return _normalize_metric_value(str(raw_value))
    return ""


def _is_scalar_metric_value(value) -> bool:
    return isinstance(value, (str, int, float)) and str(value).strip() != ""


def _extract_metric_value(value: str) -> str:
    normalized = _normalize_metric_value(value)
    if not normalized:
        return ""
    if VALUE_PATTERN.fullmatch(normalized):
        return normalized
    match = VALUE_PATTERN.search(normalized)
    if match:
        return _normalize_metric_value(match.group("value"))
    return ""


def _normalize_metric_value(value: str) -> str:
    normalized = _normalize_space(value).strip("|[]{}")
    if normalized.lower().startswith("usd "):
        return "$" + normalized[4:].strip()
    return normalized


def _resolve_report_date(timezone_name: str) -> str:
    try:
        return datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    except ZoneInfoNotFoundError:
        return datetime.now().date().isoformat()


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False
