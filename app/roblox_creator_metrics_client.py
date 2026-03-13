from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from .config import Config
from .project_metrics_models import ProjectDailyMetricsRecord, get_project_start_date, now_iso
from .retry import with_retry


ANALYTICS_QUERY_GATEWAY_URL_TEMPLATE = (
    "https://apis.roblox.com/analytics-query-gateway/v1/metrics/resource/{resource_type}/id/{resource_id}"
)
ANALYTICS_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://create.roblox.com",
    "Referer": "https://create.roblox.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
}


class RobloxCreatorMetricsClientError(RuntimeError):
    """表示 Roblox Creator 后台指标抓取失败。"""


@dataclass(frozen=True)
class MetricDefinition:
    """描述一个指标字段的别名集合。"""

    field_name: str
    aliases: tuple[str, ...]


METRIC_DEFINITIONS = (
    MetricDefinition("average_ccu", ("average ccu", "avg ccu", "avg concurrents")),
    MetricDefinition("peak_ccu", ("peak ccu", "peak concurrent users", "peak concurrents", "max ccu")),
    MetricDefinition(
        "average_session_time",
        (
            "average session time",
            "avg session time",
            "average play time",
            "average session length",
            "avg play time",
        ),
    ),
    MetricDefinition("day1_retention", ("day 1 retention", "d1 retention", "1 day retention")),
    MetricDefinition("day7_retention", ("day 7 retention", "d7 retention", "7 day retention")),
    MetricDefinition(
        "payer_conversion_rate",
        (
            "payer conversion rate",
            "payer conversion",
            "payment conversion rate",
            "pay rate",
            "cvr",
            "conversion rate",
        ),
    ),
    MetricDefinition("arppu", ("arppu", "average revenue per paying user")),
    MetricDefinition("qptr", ("qptr", "qtpr", "qualified play through rate")),
    MetricDefinition(
        "five_minute_retention",
        (
            "5 minute retention",
            "5-minute retention",
            "five minute retention",
            "new user first session retention",
        ),
    ),
    MetricDefinition(
        "home_recommendations",
        (
            "home recommendations",
            "home recommendation",
            "home recommendation impressions",
            "home recommendation count",
            "home impressions",
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
    "latestValue",
    "latest_value",
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
CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"([a-z0-9])([A-Z])")
ACRONYM_BOUNDARY_PATTERN = re.compile(r"([A-Z]+)([A-Z][a-z])")
VALUE_PATTERN = re.compile(
    r"(?P<value>(?:\$|USD\s*)?\d[\d,]*(?:\.\d+)?%?|\d+h\s*\d+m(?:\s*\d+s)?|\d+m\s*\d+s|\d+[:]\d+|\d+)",
    re.IGNORECASE,
)
DEBUG_HTML_MAX_LENGTH = 120_000
DEBUG_PAYLOAD_MAX_LENGTH = 20_000


MISSING_METRIC_PLACEHOLDER = "未获取"
ANALYTICS_STATUS_CONFIG_URL_TEMPLATE = (
    "https://apis.roblox.com/analytics-query-gateway/v1/status-config?universeId={resource_id}"
)
ANALYTICS_FEATURE_PERMISSIONS_URL_TEMPLATE = (
    "https://apis.roblox.com/developer-analytics-aggregations/v1/feature-permissions?universeId={resource_id}"
)
ANALYTICS_RESOURCE_TYPE = "RESOURCE_TYPE_UNIVERSE"
MINIMUM_REQUIRED_FIELDS = ("average_ccu", "peak_ccu")


@dataclass(frozen=True)
class MetricQuerySpec:
    """描述一个 direct analytics 指标查询。"""

    field_name: str
    metric: str
    granularity: str
    lookback_days: int
    value_type: str
    breakdown_dimensions: tuple[str, ...] = ()
    filters: tuple[dict[str, object], ...] = ()
    limit: int | None = None


@dataclass(frozen=True)
class QueryAttempt:
    """记录一次内部 analytics 请求结果，便于失败时排查。"""

    endpoint_name: str
    url: str
    method: str
    status: str
    request_excerpt: str
    payload_excerpt: str


DIRECT_QUERY_SPECS = (
    MetricQuerySpec("average_ccu", "ConcurrentPlayers", "METRIC_GRANULARITY_ONE_HOUR", 14, "daily_average"),
    MetricQuerySpec("peak_ccu", "PeakConcurrentPlayers", "METRIC_GRANULARITY_ONE_HOUR", 14, "daily_max"),
    MetricQuerySpec("average_session_time", "AverageSessionLengthMinutes", "METRIC_GRANULARITY_ONE_DAY", 14, "minutes"),
    MetricQuerySpec("day1_retention", "D1Retention", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("day7_retention", "D7Retention", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("payer_conversion_rate", "PayingUsersCVR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("arppu", "AverageRevenuePerPayingUser", "METRIC_GRANULARITY_ONE_DAY", 14, "currency"),
    MetricQuerySpec("qptr", "RFYQualifiedPTR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
)
DIRECT_QUERY_FALLBACK_SPECS = (
    MetricQuerySpec("average_session_time", "SessionDurationSecondsAvg", "METRIC_GRANULARITY_ONE_MINUTE", 1, "seconds"),
    MetricQuerySpec("day1_retention", "L7AverageForwardD1Retention", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("day7_retention", "L7AverageForwardD7Retention", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("payer_conversion_rate", "L7AveragePayingUsersCVR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("arppu", "L7AverageRevenuePerPayingUser", "METRIC_GRANULARITY_ONE_DAY", 14, "currency"),
    MetricQuerySpec("qptr", "L7AverageRFYQualifiedPTR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
)
FIVE_MINUTE_RETENTION_SPEC = MetricQuerySpec(
    "five_minute_retention",
    "TotalSessionsEndedInBucket",
    "METRIC_GRANULARITY_ONE_DAY",
    10,
    "session_bucket_ratio",
    breakdown_dimensions=("SessionTimeBucket",),
)
HOME_RECOMMENDATIONS_SPEC = MetricQuerySpec(
    "home_recommendations",
    "DailyActiveUsers",
    "METRIC_GRANULARITY_ONE_DAY",
    10,
    "breakdown_count",
    breakdown_dimensions=("AcquisitionSource",),
    filters=({"dimension": "IsNewUser", "values": ["New"], "operation": "FILTER_OPERATION_CONTAINS"},),
    limit=5,
)


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
    _csrf_token: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def fetch_project_daily_metrics(self) -> list[ProjectDailyMetricsRecord]:
        """抓取项目最近窗口内的真实日期指标序列。"""

        overview_url = self.config.roblox_creator_overview_url.strip()
        if not overview_url:
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_OVERVIEW_URL 未配置")
        if not self.config.roblox_creator_cookie.strip():
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_COOKIE 未配置")

        project_id = _extract_project_id(overview_url)
        window = _resolve_project_query_window(project_id)
        if window is None:
            return []

        start_time, end_time = window
        direct_attempts: list[QueryAttempt] = []
        metrics_by_field = self._fetch_direct_metrics(project_id, start_time, end_time, direct_attempts)
        minimum_missing = [field_name for field_name in MINIMUM_REQUIRED_FIELDS if not metrics_by_field.get(field_name)]
        missing_fields = [definition.field_name for definition in METRIC_DEFINITIONS if not metrics_by_field.get(definition.field_name)]
        debug_path = ""
        if missing_fields:
            debug_path = self._write_debug_snapshot("", metrics_by_field, missing_fields, direct_attempts)
        if minimum_missing:
            raise RobloxCreatorMetricsClientError(
                "Creator overview 页面缺少核心指标: "
                + ", ".join(minimum_missing)
                + (f"；已输出调试样本: {debug_path}" if debug_path else "")
            )

        report_dates = sorted(
            {report_date for series in metrics_by_field.values() for report_date in series.keys()},
            reverse=True,
        )
        fetched_at = now_iso()
        records: list[ProjectDailyMetricsRecord] = []
        for report_date in report_dates:
            records.append(
                ProjectDailyMetricsRecord(
                    report_date=report_date,
                    average_ccu=metrics_by_field.get("average_ccu", {}).get(report_date, ""),
                    peak_ccu=metrics_by_field.get("peak_ccu", {}).get(report_date, ""),
                    average_session_time=metrics_by_field.get("average_session_time", {}).get(report_date, ""),
                    day1_retention=metrics_by_field.get("day1_retention", {}).get(report_date, ""),
                    day7_retention=metrics_by_field.get("day7_retention", {}).get(report_date, ""),
                    payer_conversion_rate=metrics_by_field.get("payer_conversion_rate", {}).get(report_date, ""),
                    arppu=metrics_by_field.get("arppu", {}).get(report_date, ""),
                    qptr=metrics_by_field.get("qptr", {}).get(report_date, ""),
                    five_minute_retention=metrics_by_field.get("five_minute_retention", {}).get(report_date, ""),
                    home_recommendations=metrics_by_field.get("home_recommendations", {}).get(report_date, ""),
                    project_id=project_id,
                    source_url=overview_url,
                    fetched_at=fetched_at,
                )
            )
        return records

    def _fetch_direct_metrics(
        self,
        project_id: str,
        start_time: datetime,
        end_time: datetime,
        attempts: list[QueryAttempt],
    ) -> dict[str, dict[str, str]]:
        """优先通过真实内部 analytics 接口抓取最近窗口内的日期序列。"""

        metrics: dict[str, dict[str, str]] = {}
        self._fetch_feature_permissions(project_id, attempts)
        self._fetch_status_config(project_id, attempts)

        for spec in DIRECT_QUERY_SPECS:
            series = self._query_metric_series(project_id, spec, start_time, end_time, attempts)
            if series:
                metrics[spec.field_name] = series
        for spec in DIRECT_QUERY_FALLBACK_SPECS:
            if metrics.get(spec.field_name):
                continue
            series = self._query_metric_series(project_id, spec, start_time, end_time, attempts)
            if series:
                metrics[spec.field_name] = series
        if not metrics.get("five_minute_retention"):
            series = self._query_metric_series(project_id, FIVE_MINUTE_RETENTION_SPEC, start_time, end_time, attempts)
            if series:
                metrics["five_minute_retention"] = series
        home_recommendations = self._query_metric_series(project_id, HOME_RECOMMENDATIONS_SPEC, start_time, end_time, attempts)
        if home_recommendations:
            metrics["home_recommendations"] = home_recommendations
        return metrics

    def _fetch_feature_permissions(self, project_id: str, attempts: list[QueryAttempt]) -> None:
        """探测项目是否拥有 analytics 页面权限。"""

        url = ANALYTICS_FEATURE_PERMISSIONS_URL_TEMPLATE.format(resource_id=project_id)
        try:
            payload = self._request_json("GET", url, json_body=None)
        except RobloxCreatorMetricsClientError as exc:
            attempts.append(QueryAttempt("feature_permissions", url, "GET", f"error: {exc}", "", ""))
            return
        attempts.append(QueryAttempt("feature_permissions", url, "GET", "ok", "", _truncate_json(payload)))

    def _fetch_status_config(self, project_id: str, attempts: list[QueryAttempt]) -> None:
        """抓取 status config，方便后续定位可用指标。"""

        url = ANALYTICS_STATUS_CONFIG_URL_TEMPLATE.format(resource_id=project_id)
        try:
            payload = self._request_json("GET", url, json_body=None)
        except RobloxCreatorMetricsClientError as exc:
            attempts.append(QueryAttempt("status_config", url, "GET", f"error: {exc}", "", ""))
            return
        attempts.append(QueryAttempt("status_config", url, "GET", "ok", "", _truncate_json(payload)))

    def _query_metric_series(
        self,
        project_id: str,
        spec: MetricQuerySpec,
        start_time: datetime,
        end_time: datetime,
        attempts: list[QueryAttempt],
    ) -> dict[str, str]:
        """按指标配置请求 analytics-query-gateway，并返回按日期组织的值。"""

        url = ANALYTICS_QUERY_GATEWAY_URL_TEMPLATE.format(resource_type=ANALYTICS_RESOURCE_TYPE, resource_id=project_id)
        request_payload = self._build_metric_request_payload(project_id, spec, start_time, end_time)
        try:
            payload = self._request_json("POST", url, json_body=request_payload)
        except RobloxCreatorMetricsClientError as exc:
            attempts.append(QueryAttempt(spec.metric, url, "POST", f"error: {exc}", _truncate_json(request_payload), ""))
            return {}
        attempts.append(QueryAttempt(spec.metric, url, "POST", "ok", _truncate_json(request_payload), _truncate_json(payload)))
        return self._extract_metric_series_from_query_result(payload, spec)

    def _build_metric_request_payload(
        self,
        project_id: str,
        spec: MetricQuerySpec,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, object]:
        """组装 direct analytics 请求体。"""

        query: dict[str, object] = {
            "metric": spec.metric,
            "granularity": spec.granularity,
            "startTime": start_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "endTime": end_time.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "breakdown": [{"dimensions": list(spec.breakdown_dimensions)}] if spec.breakdown_dimensions else [],
        }
        if spec.filters:
            query["filter"] = [dict(item) for item in spec.filters]
        if spec.limit is not None:
            query["limit"] = spec.limit
        return {"resourceType": ANALYTICS_RESOURCE_TYPE, "resourceId": project_id, "query": query}

    def _extract_metric_series_from_query_result(self, payload: object, spec: MetricQuerySpec) -> dict[str, str]:
        """从 queryResult 中抽取并格式化按日期组织的指标序列。"""

        values = self._extract_query_values(payload)
        if spec.value_type == "session_bucket_ratio":
            return _format_series(_extract_session_bucket_retention_series(values, threshold_seconds=300), _format_ratio)
        if spec.value_type == "breakdown_count":
            return _format_series(_extract_breakdown_daily_counts(values, "HomeRecommendation"), _format_count)

        datapoints = _flatten_numeric_datapoints(values)
        if not datapoints:
            return {}
        if spec.value_type == "daily_average":
            return _format_series(_aggregate_daily_values(datapoints, "average"), _format_count)
        if spec.value_type == "daily_max":
            return _format_series(_aggregate_daily_values(datapoints, "max"), _format_count)

        latest_values = _aggregate_daily_values(datapoints, "latest")
        if spec.field_name == "day1_retention":
            latest_values = _shift_series_dates(latest_values, days=-1)
        if spec.field_name == "day7_retention":
            latest_values = _shift_series_dates(latest_values, days=-7)
        if spec.value_type == "ratio":
            return _format_series(latest_values, _format_ratio)
        if spec.value_type == "currency":
            return _format_series(latest_values, _format_currency)
        if spec.value_type == "minutes":
            return _format_series(latest_values, _format_duration_from_minutes)
        if spec.value_type == "seconds":
            return _format_series(latest_values, _format_duration_from_seconds)
        return _format_series(latest_values, lambda value: _normalize_metric_value(str(value)))

    def _extract_query_values(self, payload: object) -> list[dict[str, object]]:
        """从 analytics gateway 响应中提取 values 列表。"""

        if not isinstance(payload, dict):
            return []
        operation = payload.get("operation")
        if isinstance(operation, dict):
            query_result = operation.get("queryResult")
            if isinstance(query_result, dict):
                values = query_result.get("values")
                if isinstance(values, list):
                    return [item for item in values if isinstance(item, dict)]
        result = payload.get("result")
        if isinstance(result, dict):
            values = result.get("values")
            if isinstance(values, list):
                return [item for item in values if isinstance(item, dict)]
        return []

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

    def _request_json(self, method: str, url: str, *, json_body: dict[str, object] | None):
        """发送 JSON 请求，并在需要时自动刷新 x-csrf-token。"""

        def _call():
            return self._send_json_request(method, url, json_body)

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
            raise RobloxCreatorMetricsClientError(f"请求 analytics 接口失败: {url}") from exc

    def _send_json_request(self, method: str, url: str, json_body: dict[str, object] | None):
        """执行一次真实 HTTP 请求。"""

        assert self.session is not None
        headers = dict(ANALYTICS_HEADERS)
        if method.upper() == "GET":
            headers.pop("Content-Type", None)
        elif self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token

        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            cookies={".ROBLOSECURITY": self.config.roblox_creator_cookie},
            timeout=self.config.request_timeout_seconds,
            allow_redirects=True,
        )
        if response.status_code == 403:
            csrf_token = response.headers.get("x-csrf-token", "")
            if csrf_token and csrf_token != self._csrf_token and method.upper() != "GET":
                self._csrf_token = csrf_token
                retry_headers = dict(headers)
                retry_headers["x-csrf-token"] = csrf_token
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=retry_headers,
                    json=json_body,
                    cookies={".ROBLOSECURITY": self.config.roblox_creator_cookie},
                    timeout=self.config.request_timeout_seconds,
                    allow_redirects=True,
                )
        if response.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {response.status_code}: {response.text[:400]}",
                response=response,
            )
        return response.json()

    def _extract_metrics_from_html(self, html_text: str) -> dict[str, str]:
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
            label_fields = [
                "label",
                "name",
                "title",
                "metric",
                "heading",
                "header",
                "metricName",
                "metric_name",
                "displayName",
                "display_name",
            ]
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
        direct_attempts: list[QueryAttempt],
    ) -> str:
        target_dir = Path(self.config.output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        debug_path = target_dir / "creator_overview_debug.json"
        parser = _VisibleTextParser()
        parser.feed(html_text)
        payload = {
            "captured_metrics": metrics,
            "missing_fields": missing_fields,
            "direct_query_attempts": [
                {
                    "endpoint_name": attempt.endpoint_name,
                    "url": attempt.url,
                    "method": attempt.method,
                    "status": attempt.status,
                    "request_excerpt": attempt.request_excerpt,
                    "payload_excerpt": attempt.payload_excerpt,
                }
                for attempt in direct_attempts
            ],
            "html_excerpt": html_text[:DEBUG_HTML_MAX_LENGTH],
            "visible_text_excerpt": parser.segments[:200],
            "script_excerpt": [item[:DEBUG_PAYLOAD_MAX_LENGTH] for item in _extract_script_contents(html_text)[:10]],
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


def _has_missing_metrics(metrics: dict[str, str]) -> bool:
    return any(not metrics.get(definition.field_name) for definition in METRIC_DEFINITIONS)


def _truncate_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)[:DEBUG_PAYLOAD_MAX_LENGTH]


def _match_metric_alias(raw_label: str) -> str:
    normalized = _normalize_label(raw_label)
    for definition in METRIC_DEFINITIONS:
        if normalized in definition.aliases:
            return definition.field_name
    return ""


def _normalize_label(value: str) -> str:
    value = str(value)
    value = ACRONYM_BOUNDARY_PATTERN.sub(r"\1 \2", value)
    value = CAMEL_CASE_BOUNDARY_PATTERN.sub(r"\1 \2", value)
    value = re.sub(r"[^A-Za-z0-9%]+", " ", value)
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
        if key in {
            "label",
            "name",
            "title",
            "metric",
            "heading",
            "header",
            "metricName",
            "metric_name",
            "displayName",
            "display_name",
        }:
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


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {403, 408, 409, 425, 429, 500, 502, 503, 504}
    return False


def _parse_iso_datetime(raw_value: str) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _coerce_numeric(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _flatten_numeric_datapoints(values: list[dict[str, object]]) -> list[tuple[datetime, float]]:
    datapoints: list[tuple[datetime, float]] = []
    for series in values:
        for point in series.get("dataPoints", []):
            if not isinstance(point, dict):
                continue
            parsed = _parse_iso_datetime(str(point.get("time", "")))
            numeric = _coerce_numeric(point.get("value"))
            if parsed is None or numeric is None:
                continue
            datapoints.append((parsed, numeric))
    datapoints.sort(key=lambda item: item[0])
    return datapoints


def _latest_value(datapoints: list[tuple[datetime, float]]) -> float | None:
    if not datapoints:
        return None
    return datapoints[-1][1]


def _latest_day_average(datapoints: list[tuple[datetime, float]]) -> float:
    latest_day = datapoints[-1][0].date()
    same_day = [value for timestamp, value in datapoints if timestamp.date() == latest_day]
    return sum(same_day) / max(1, len(same_day))


def _latest_day_max(datapoints: list[tuple[datetime, float]]) -> float:
    latest_day = datapoints[-1][0].date()
    same_day = [value for timestamp, value in datapoints if timestamp.date() == latest_day]
    return max(same_day) if same_day else datapoints[-1][1]


def _format_count(value: float) -> str:
    return format(int(round(value)), ",")


def _format_ratio(value: float) -> str:
    percent = value * 100 if value <= 1.0 else value
    text = f"{percent:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def _format_currency(value: float) -> str:
    return f"${value:.2f}"


def _format_duration_from_minutes(value: float) -> str:
    return _format_duration_from_seconds(value * 60)


def _format_duration_from_seconds(value: float) -> str:
    total_seconds = max(0, int(round(value)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _contains_breakdown_value(breakdown_values: list[object], expected_value: str) -> bool:
    for item in breakdown_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("value", "")) == expected_value:
            return True
    return False


def _extract_session_bucket_retention_ratio(values: list[dict[str, object]], threshold_seconds: int) -> float | None:
    """从 SessionTimeBucket 分桶中推导指定时长阈值的留存占比。"""

    bucket_counts: dict[int, float] = {}
    for series in values:
        bucket_seconds = _extract_session_bucket_seconds(series.get("breakdownValue", []))
        if bucket_seconds is None:
            continue
        datapoints = _flatten_numeric_datapoints([series])
        latest_value = _latest_value(datapoints)
        if latest_value is None or latest_value <= 0:
            continue
        bucket_counts[bucket_seconds] = latest_value
    if not bucket_counts:
        return None

    base_bucket = min(bucket_counts)
    denominator = bucket_counts.get(base_bucket)
    if denominator is None or denominator <= 0:
        return None

    retained_bucket = min(bucket_counts, key=lambda bucket: (abs(bucket - threshold_seconds), bucket))
    numerator = bucket_counts.get(retained_bucket)
    if numerator is None or numerator < 0:
        return None
    return numerator / denominator


def _extract_session_bucket_seconds(breakdown_values: object) -> int | None:
    """从 SessionTimeBucket 的 breakdownValue 中提取秒数阈值。"""

    if not isinstance(breakdown_values, list):
        return None
    for item in breakdown_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("dimension", "")).strip() != "SessionTimeBucket":
            continue
        raw_value = str(item.get("value", "")).strip()
        if not raw_value:
            return None
        try:
            return int(float(raw_value))
        except ValueError:
            return None
    return None


def _resolve_project_query_window(project_id: str) -> tuple[datetime, datetime] | None:
    end_time = _utc_midnight_now()
    end_date = (end_time - timedelta(days=1)).date()
    start_date = end_date - timedelta(days=9)
    project_start_date = get_project_start_date(project_id)
    if project_start_date is not None and project_start_date > start_date:
        start_date = project_start_date
    if start_date > end_date:
        return None
    start_time = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    return start_time, end_time


def _aggregate_daily_values(datapoints: list[tuple[datetime, float]], mode: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for timestamp, value in datapoints:
        grouped.setdefault(timestamp.date().isoformat(), []).append(value)
    if mode == "average":
        return {report_date: sum(values) / len(values) for report_date, values in grouped.items() if values}
    if mode == "max":
        return {report_date: max(values) for report_date, values in grouped.items() if values}
    return {report_date: values[-1] for report_date, values in grouped.items() if values}


def _shift_series_dates(series: dict[str, float], days: int) -> dict[str, float]:
    shifted: dict[str, float] = {}
    for report_date, value in series.items():
        shifted_date = date.fromisoformat(report_date) + timedelta(days=days)
        shifted[shifted_date.isoformat()] = value
    return shifted


def _format_series(series: dict[str, float], formatter) -> dict[str, str]:
    return {report_date: formatter(value) for report_date, value in sorted(series.items())}


def _extract_session_bucket_retention_series(values: list[dict[str, object]], threshold_seconds: int) -> dict[str, float]:
    bucket_counts_by_date: dict[str, dict[int, float]] = {}
    for series in values:
        bucket_seconds = _extract_session_bucket_seconds(series.get("breakdownValue", []))
        if bucket_seconds is None:
            continue
        for timestamp, value in _flatten_numeric_datapoints([series]):
            report_date = timestamp.date().isoformat()
            bucket_counts_by_date.setdefault(report_date, {})[bucket_seconds] = value

    ratios: dict[str, float] = {}
    for report_date, bucket_counts in bucket_counts_by_date.items():
        if not bucket_counts:
            continue
        base_bucket = min(bucket_counts)
        denominator = bucket_counts.get(base_bucket)
        if denominator is None or denominator <= 0:
            continue
        retained_bucket = min(bucket_counts, key=lambda bucket: (abs(bucket - threshold_seconds), bucket))
        numerator = bucket_counts.get(retained_bucket)
        if numerator is None or numerator < 0:
            continue
        ratios[report_date] = numerator / denominator
    return ratios


def _extract_breakdown_daily_counts(values: list[dict[str, object]], expected_value: str) -> dict[str, float]:
    counts: dict[str, float] = {}
    for series in values:
        if not _contains_breakdown_value(series.get("breakdownValue", []), expected_value):
            continue
        for timestamp, value in _flatten_numeric_datapoints([series]):
            counts[timestamp.date().isoformat()] = counts.get(timestamp.date().isoformat(), 0.0) + value
    return counts


def _utc_midnight_now() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
