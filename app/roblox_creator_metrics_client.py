from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from .config import Config
from .project_metrics_models import (
    ProjectDailyMetricsRecord,
    get_project_required_fields,
    get_project_start_date,
    now_iso,
)
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
    MetricDefinition("client_crash_rate", ("client crash rate", "crash rate", "client crash rate 15m")),
    MetricDefinition("client_memory_usage", ("client memory usage", "client memory", "memory usage")),
    MetricDefinition("client_frame_rate", ("client frame rate", "client fps", "frame rate", "fps")),
    MetricDefinition("server_crashes", ("server crashes", "server crash count")),
    MetricDefinition("server_memory_usage", ("server memory usage", "server memory")),
    MetricDefinition("server_frame_rate", ("server frame rate", "server fps")),
)
INLINE_JSON_PATTERN = re.compile(r"<script[^>]*>(?P<content>.*?)</script>", re.IGNORECASE | re.DOTALL)
CAMEL_CASE_BOUNDARY_PATTERN = re.compile(r"([a-z0-9])([A-Z])")
ACRONYM_BOUNDARY_PATTERN = re.compile(r"([A-Z]+)([A-Z][a-z])")
DEBUG_HTML_MAX_LENGTH = 120_000
DEBUG_PAYLOAD_MAX_LENGTH = 20_000

ANALYTICS_STATUS_CONFIG_URL_TEMPLATE = (
    "https://apis.roblox.com/analytics-query-gateway/v1/status-config?universeId={resource_id}"
)
ANALYTICS_FEATURE_PERMISSIONS_URL_TEMPLATE = (
    "https://apis.roblox.com/developer-analytics-aggregations/v1/feature-permissions?universeId={resource_id}"
)
ANALYTICS_METADATA_URL = "https://apis.roblox.com/analytics-query-gateway/v1/metrics/metadata"
ANALYTICS_BENCHMARK_SCORECARD_URL_TEMPLATE = (
    "https://apis.roblox.com/universe-analytics-insights/v2/universes/{resource_id}/insights/benchmark-scorecard?metric={metric}"
)
ANALYTICS_RESOURCE_TYPE = "RESOURCE_TYPE_UNIVERSE"


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


@dataclass(frozen=True)
class BenchmarkScorecardSpec:
    """描述 benchmark-scorecard 与日报字段之间的映射。"""

    field_name: str
    metric: str


DIRECT_QUERY_SPECS = (
    MetricQuerySpec("peak_ccu", "PeakConcurrentPlayers", "METRIC_GRANULARITY_ONE_DAY", 14, "integer"),
    MetricQuerySpec("average_session_time", "AveragePlayTimeMinutesPerDAU", "METRIC_GRANULARITY_ONE_DAY", 14, "minutes"),
    MetricQuerySpec("payer_conversion_rate", "PayingUsersCVR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("arppu", "AverageRevenuePerPayingUser", "METRIC_GRANULARITY_ONE_DAY", 14, "currency"),
    MetricQuerySpec("qptr", "RFYQualifiedPTR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("client_crash_rate", "ClientCrashRate15m", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("client_memory_usage", "ClientMemoryUsageAvg", "METRIC_GRANULARITY_ONE_DAY", 14, "memory"),
    MetricQuerySpec("client_frame_rate", "ClientFpsAvg", "METRIC_GRANULARITY_ONE_DAY", 14, "frame_rate"),
    MetricQuerySpec("server_crashes", "ServerCrashCount", "METRIC_GRANULARITY_ONE_DAY", 14, "daily_sum"),
    MetricQuerySpec("server_memory_usage", "ServerMemoryUsageAvg", "METRIC_GRANULARITY_ONE_DAY", 14, "memory"),
    MetricQuerySpec("server_frame_rate", "ServerFrameRateAvg", "METRIC_GRANULARITY_ONE_DAY", 14, "frame_rate"),
)
DIRECT_QUERY_FALLBACK_SPECS = (
    MetricQuerySpec("average_session_time", "SessionDurationSecondsAvg", "METRIC_GRANULARITY_ONE_MINUTE", 1, "seconds"),
    MetricQuerySpec("payer_conversion_rate", "L7AveragePayingUsersCVR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
    MetricQuerySpec("arppu", "L7AverageRevenuePerPayingUser", "METRIC_GRANULARITY_ONE_DAY", 14, "currency"),
    MetricQuerySpec("qptr", "L7AverageRFYQualifiedPTR", "METRIC_GRANULARITY_ONE_DAY", 14, "ratio"),
)
COHORT_RETENTION_SPEC = MetricQuerySpec(
    "cohort_retention",
    "DailyCohortRetention",
    "METRIC_GRANULARITY_ONE_DAY",
    14,
    "cohort_retention_ratio",
    breakdown_dimensions=("CohortDay",),
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
    "UniqueUsersWithImpressions",
    "METRIC_GRANULARITY_ONE_DAY",
    10,
    "breakdown_count",
    breakdown_dimensions=("AcquisitionSource",),
)
PROJECT_METRIC_RANK_FIELDS = (
    "average_session_time",
    "day1_retention",
    "day7_retention",
    "payer_conversion_rate",
    "arppu",
)
BENCHMARK_SCORECARD_SPECS = (
    BenchmarkScorecardSpec("average_session_time", "L7AveragePlayTimeMinutesPerDAU"),
    BenchmarkScorecardSpec("day1_retention", "L7AverageForwardD1Retention"),
    BenchmarkScorecardSpec("day7_retention", "L7AverageForwardD7Retention"),
    BenchmarkScorecardSpec("payer_conversion_rate", "L7AveragePayingUsersCVR"),
    BenchmarkScorecardSpec("arppu", "L7AverageRevenuePerPayingUser"),
)
PERCENTILE_KEYWORDS = (
    "percentile",
    "peer percentile",
    "benchmark percentile",
    "peer group percentile",
    "experience percentile",
    "game percentile",
    "genre percentile",
    "similar experience percentile",
)
PERCENTILE_CONTAINER_KEYWORDS = (
    "benchmark",
    "comparison",
    "peer",
    "genre",
    "similar",
    "percentile",
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


@dataclass(frozen=True)
class MetricSeriesResult:
    """描述某个指标的每日值序列与同类百分位序列。"""

    values: dict[str, str]
    ranks: dict[str, str]


@dataclass
class RobloxCreatorMetricsClient:
    """负责抓取 Roblox Creator 后台项目 overview 指标。"""

    config: Config
    session: requests.Session | None = None
    _csrf_token: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def fetch_project_daily_metrics(self, overview_url: str | None = None) -> list[ProjectDailyMetricsRecord]:
        """抓取项目最近窗口内的真实日期指标序列。"""

        resolved_overview_url = (overview_url or self.config.roblox_creator_overview_url).strip()
        if not resolved_overview_url:
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_OVERVIEW_URL 未配置")
        if not self.config.roblox_creator_cookie.strip():
            raise RobloxCreatorMetricsClientError("ROBLOX_CREATOR_COOKIE 未配置")

        project_id = _extract_project_id(resolved_overview_url)
        business_timezone = _resolve_business_timezone(self.config.feishu_timezone)
        window = _resolve_project_query_window(project_id, business_timezone)
        if window is None:
            return []

        start_time, end_time, start_date, end_date = window
        direct_attempts: list[QueryAttempt] = []
        metrics_by_field, metric_ranks_by_field = self._fetch_direct_metrics(
            project_id,
            start_time,
            end_time,
            direct_attempts,
            business_timezone,
            start_date,
            end_date,
        )
        benchmark_metric_ranks = self._fetch_benchmark_metric_ranks(
            project_id,
            direct_attempts,
            business_timezone,
            start_date,
            end_date,
        )
        for field_name, rank_series in benchmark_metric_ranks.items():
            if rank_series:
                metric_ranks_by_field[field_name] = rank_series
        required_fields = get_project_required_fields(project_id)
        minimum_missing = [field_name for field_name in required_fields if not metrics_by_field.get(field_name)]
        missing_fields = [definition.field_name for definition in METRIC_DEFINITIONS if not metrics_by_field.get(definition.field_name)]
        debug_path = ""
        if minimum_missing:
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
                    peak_ccu=metrics_by_field.get("peak_ccu", {}).get(report_date, ""),
                    average_session_time=metrics_by_field.get("average_session_time", {}).get(report_date, ""),
                    average_session_time_rank=metric_ranks_by_field.get("average_session_time", {}).get(report_date, ""),
                    day1_retention=metrics_by_field.get("day1_retention", {}).get(report_date, ""),
                    day1_retention_rank=metric_ranks_by_field.get("day1_retention", {}).get(report_date, ""),
                    day7_retention=metrics_by_field.get("day7_retention", {}).get(report_date, ""),
                    day7_retention_rank=metric_ranks_by_field.get("day7_retention", {}).get(report_date, ""),
                    payer_conversion_rate=metrics_by_field.get("payer_conversion_rate", {}).get(report_date, ""),
                    payer_conversion_rate_rank=metric_ranks_by_field.get("payer_conversion_rate", {}).get(report_date, ""),
                    arppu=metrics_by_field.get("arppu", {}).get(report_date, ""),
                    arppu_rank=metric_ranks_by_field.get("arppu", {}).get(report_date, ""),
                    qptr=metrics_by_field.get("qptr", {}).get(report_date, ""),
                    five_minute_retention=metrics_by_field.get("five_minute_retention", {}).get(report_date, ""),
                    home_recommendations=metrics_by_field.get("home_recommendations", {}).get(report_date, ""),
                    client_crash_rate=metrics_by_field.get("client_crash_rate", {}).get(report_date, ""),
                    client_memory_usage=metrics_by_field.get("client_memory_usage", {}).get(report_date, ""),
                    client_frame_rate=metrics_by_field.get("client_frame_rate", {}).get(report_date, ""),
                    server_crashes=metrics_by_field.get("server_crashes", {}).get(report_date, ""),
                    server_memory_usage=metrics_by_field.get("server_memory_usage", {}).get(report_date, ""),
                    server_frame_rate=metrics_by_field.get("server_frame_rate", {}).get(report_date, ""),
                    project_id=project_id,
                    source_url=resolved_overview_url,
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
        business_timezone: timezone | ZoneInfo,
        start_date: date,
        end_date: date,
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        """优先通过真实内部 analytics 接口抓取最近窗口内的日期序列。"""

        metrics: dict[str, dict[str, str]] = {}
        metric_ranks: dict[str, dict[str, str]] = {}
        self._fetch_feature_permissions(project_id, attempts)
        self._fetch_status_config(project_id, attempts)
        metadata_by_metric = self._fetch_metric_metadata(project_id, attempts)

        for spec in DIRECT_QUERY_SPECS:
            series = self._query_metric_series(
                project_id,
                spec,
                start_time,
                end_time,
                attempts,
                business_timezone,
                start_date,
                end_date,
                metadata_by_metric,
            )
            if series.values:
                metrics[spec.field_name] = series.values
            if spec.field_name in PROJECT_METRIC_RANK_FIELDS and series.ranks:
                metric_ranks[spec.field_name] = series.ranks
        for spec in DIRECT_QUERY_FALLBACK_SPECS:
            if metrics.get(spec.field_name):
                continue
            series = self._query_metric_series(
                project_id,
                spec,
                start_time,
                end_time,
                attempts,
                business_timezone,
                start_date,
                end_date,
                metadata_by_metric,
            )
            if series.values:
                metrics[spec.field_name] = series.values
            if spec.field_name in PROJECT_METRIC_RANK_FIELDS and series.ranks:
                metric_ranks[spec.field_name] = series.ranks
        cohort_retention = self._query_metric_series(
            project_id,
            COHORT_RETENTION_SPEC,
            start_time,
            end_time,
            attempts,
            business_timezone,
            start_date,
            end_date,
            metadata_by_metric,
        )
        if cohort_retention.values:
            metrics["day1_retention"] = _filter_metric_series(
                _extract_cohort_retention_day(cohort_retention.values, 1),
                "day1_retention",
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric="DailyCohortRetention",
                cohort_day=1,
            )
            metrics["day7_retention"] = _filter_metric_series(
                _extract_cohort_retention_day(cohort_retention.values, 7),
                "day7_retention",
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric="DailyCohortRetention",
                cohort_day=7,
            )
        if cohort_retention.ranks:
            metric_ranks["day1_retention"] = _filter_metric_series(
                _extract_cohort_retention_day(cohort_retention.ranks, 1),
                "day1_retention",
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric="DailyCohortRetention",
                cohort_day=1,
            )
            metric_ranks["day7_retention"] = _filter_metric_series(
                _extract_cohort_retention_day(cohort_retention.ranks, 7),
                "day7_retention",
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric="DailyCohortRetention",
                cohort_day=7,
            )
        if not metrics.get("five_minute_retention"):
            series = self._query_metric_series(
                project_id,
                FIVE_MINUTE_RETENTION_SPEC,
                start_time,
                end_time,
                attempts,
                business_timezone,
                start_date,
                end_date,
                metadata_by_metric,
            )
            if series.values:
                metrics["five_minute_retention"] = series.values
        home_recommendations = self._query_metric_series(
            project_id,
            HOME_RECOMMENDATIONS_SPEC,
            start_time,
            end_time,
            attempts,
            business_timezone,
            start_date,
            end_date,
            metadata_by_metric,
        )
        if home_recommendations.values:
            metrics["home_recommendations"] = home_recommendations.values
        return metrics, metric_ranks

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

    def _fetch_metric_metadata(self, project_id: str, attempts: list[QueryAttempt]) -> dict[str, date]:
        """抓取指标最新可用日期，避免把未成熟数据写进表。"""

        del project_id
        requested_metrics = sorted({spec.metric for spec in DIRECT_QUERY_SPECS + DIRECT_QUERY_FALLBACK_SPECS + (COHORT_RETENTION_SPEC, FIVE_MINUTE_RETENTION_SPEC, HOME_RECOMMENDATIONS_SPEC)})
        request_payload = {"query": {"metrics": requested_metrics}}
        try:
            payload = self._request_json("POST", ANALYTICS_METADATA_URL, json_body=request_payload)
        except RobloxCreatorMetricsClientError as exc:
            attempts.append(QueryAttempt("metrics_metadata", ANALYTICS_METADATA_URL, "POST", f"error: {exc}", _truncate_json(request_payload), ""))
            return {}
        attempts.append(QueryAttempt("metrics_metadata", ANALYTICS_METADATA_URL, "POST", "ok", _truncate_json(request_payload), _truncate_json(payload)))
        return _extract_metric_latest_dates(payload)

    def _query_metric_series(
        self,
        project_id: str,
        spec: MetricQuerySpec,
        start_time: datetime,
        end_time: datetime,
        attempts: list[QueryAttempt],
        business_timezone: timezone | ZoneInfo,
        start_date: date,
        end_date: date,
        metadata_by_metric: dict[str, date],
    ) -> MetricSeriesResult:
        """按指标配置请求 analytics-query-gateway，并返回按日期组织的值。"""

        url = ANALYTICS_QUERY_GATEWAY_URL_TEMPLATE.format(resource_type=ANALYTICS_RESOURCE_TYPE, resource_id=project_id)
        request_payload = self._build_metric_request_payload(project_id, spec, start_time, end_time)
        try:
            payload = self._request_json("POST", url, json_body=request_payload)
            payload = self._poll_query_result(url, request_payload, payload)
        except RobloxCreatorMetricsClientError as exc:
            attempts.append(QueryAttempt(spec.metric, url, "POST", f"error: {exc}", _truncate_json(request_payload), ""))
            return MetricSeriesResult(values={}, ranks={})
        attempts.append(QueryAttempt(spec.metric, url, "POST", "ok", _truncate_json(request_payload), _truncate_json(payload)))
        series = self._extract_metric_series_from_query_result(payload, spec, business_timezone)
        if spec.value_type == "cohort_retention_ratio":
            return series
        return MetricSeriesResult(
            values=_filter_metric_series(
                series.values,
                spec.field_name,
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric=spec.metric,
            ),
            ranks=_filter_metric_series(
                series.ranks,
                spec.field_name,
                project_id,
                start_date,
                end_date,
                metadata_by_metric,
                source_metric=spec.metric,
            ),
        )

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


    def _poll_query_result(self, url: str, request_payload: dict[str, object], payload: object) -> object:
        """对异步 query 轮询同一接口，直到返回 done=true 或达到重试上限。"""

        operation = payload.get("operation") if isinstance(payload, dict) else None
        if not isinstance(operation, dict) or operation.get("done") is True:
            return payload

        attempts = max(1, self.config.retry_max_attempts)
        for index in range(1, attempts + 1):
            backoff_seconds = max(0.0, self.config.retry_backoff_seconds) * index
            if backoff_seconds > 0:
                time.sleep(backoff_seconds)
            payload = self._request_json("POST", url, json_body=request_payload)
            operation = payload.get("operation") if isinstance(payload, dict) else None
            if not isinstance(operation, dict) or operation.get("done") is True:
                return payload

        return payload

    def _extract_metric_series_from_query_result(
        self,
        payload: object,
        spec: MetricQuerySpec,
        business_timezone: timezone | ZoneInfo,
    ) -> MetricSeriesResult:
        """从 queryResult 中抽取并格式化按日期组织的指标序列。"""

        values = self._extract_query_values(payload)
        if spec.value_type == "session_bucket_ratio":
            return MetricSeriesResult(
                values=_format_series(
                    _extract_session_bucket_retention_series(values, threshold_seconds=300, business_timezone=business_timezone),
                    _format_ratio,
                ),
                ranks={},
            )
        if spec.value_type == "breakdown_count":
            return MetricSeriesResult(
                values=_format_series(
                    _extract_breakdown_daily_counts(values, "Home Recommendation", business_timezone, aliases=("HomeRecommendation",)),
                    _format_count,
                ),
                ranks={},
            )
        if spec.value_type == "cohort_retention_ratio":
            return MetricSeriesResult(
                values=_extract_cohort_retention_series(values, business_timezone),
                ranks=_extract_cohort_retention_rank_series(values, business_timezone),
            )

        datapoints = _flatten_numeric_datapoints(values)
        ranks = _extract_percentile_rank_series(values, business_timezone)
        if not datapoints:
            return MetricSeriesResult(values={}, ranks=ranks)
        if spec.value_type == "daily_average":
            return MetricSeriesResult(
                values=_format_series(_aggregate_daily_values(datapoints, "average", business_timezone), _format_count),
                ranks=ranks,
            )
        if spec.value_type == "memory":
            return MetricSeriesResult(
                values=_format_series(_aggregate_daily_values(datapoints, "average", business_timezone), _format_memory_usage),
                ranks=ranks,
            )
        if spec.value_type == "frame_rate":
            return MetricSeriesResult(
                values=_format_series(_aggregate_daily_values(datapoints, "average", business_timezone), _format_frame_rate),
                ranks=ranks,
            )
        if spec.value_type == "daily_sum":
            return MetricSeriesResult(
                values=_format_series(_aggregate_daily_values(datapoints, "sum", business_timezone), _format_count),
                ranks=ranks,
            )
        if spec.value_type == "daily_max":
            return MetricSeriesResult(
                values=_format_series(_aggregate_daily_values(datapoints, "max", business_timezone), _format_count),
                ranks=ranks,
            )

        latest_values = _aggregate_daily_values(datapoints, "latest", business_timezone)
        if spec.value_type == "integer":
            return MetricSeriesResult(values=_format_series(latest_values, _format_count), ranks=ranks)
        if spec.value_type == "ratio":
            return MetricSeriesResult(values=_format_series(latest_values, _format_ratio), ranks=ranks)
        if spec.value_type == "currency":
            return MetricSeriesResult(values=_format_series(latest_values, _format_currency), ranks=ranks)
        if spec.value_type == "minutes":
            return MetricSeriesResult(values=_format_series(latest_values, _format_duration_from_minutes), ranks=ranks)
        if spec.value_type == "seconds":
            return MetricSeriesResult(values=_format_series(latest_values, _format_duration_from_seconds), ranks=ranks)
        return MetricSeriesResult(
            values=_format_series(latest_values, lambda value: _normalize_metric_value(str(value))),
            ranks=ranks,
        )

    def _fetch_benchmark_metric_ranks(
        self,
        project_id: str,
        attempts: list[QueryAttempt],
        business_timezone: timezone | ZoneInfo,
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[str, str]]:
        """抓取 overview 页面 benchmark-scorecard 接口返回的同类百分位。"""

        metric_ranks: dict[str, dict[str, str]] = {}
        empty_metadata: dict[str, date] = {}
        for spec in BENCHMARK_SCORECARD_SPECS:
            url = ANALYTICS_BENCHMARK_SCORECARD_URL_TEMPLATE.format(
                resource_id=project_id,
                metric=spec.metric,
            )
            try:
                payload = self._request_json("GET", url, json_body=None)
            except RobloxCreatorMetricsClientError as exc:
                attempts.append(QueryAttempt(spec.metric, url, "GET", f"error: {exc}", "", ""))
                continue
            attempts.append(QueryAttempt(spec.metric, url, "GET", "ok", "", _truncate_json(payload)))
            rank_series = _extract_benchmark_scorecard_rank_series(payload, business_timezone)
            if not rank_series:
                continue
            filtered_rank_series = _filter_metric_series(
                rank_series,
                spec.field_name,
                project_id,
                start_date,
                end_date,
                empty_metadata,
                source_metric="",
            )
            if filtered_rank_series:
                metric_ranks[spec.field_name] = filtered_rank_series
        return metric_ranks

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


def _extract_benchmark_scorecard_rank_series(
    payload: object,
    business_timezone: timezone | ZoneInfo,
) -> dict[str, str]:
    """从 benchmark-scorecard 响应中提取日期到百分位的映射。"""

    if not isinstance(payload, dict):
        return {}
    report_date = _resolve_report_date_from_payload(payload, business_timezone)
    if not report_date:
        return {}
    rank_text = _extract_benchmark_scorecard_rank(payload)
    if not rank_text:
        return {}
    return {report_date: rank_text}


def _extract_benchmark_scorecard_rank(payload: object) -> str:
    """优先读取 scorecard 顶层推荐百分位，缺失时再回退到备选 benchmark。"""

    if not isinstance(payload, dict):
        return ""
    top_level_rank = _format_percentile_rank(payload.get("currentPercentile"))
    if top_level_rank:
        return top_level_rank

    recommended_type = str(payload.get("recommendedType", "")).strip()
    available_benchmarks = payload.get("availableBenchmarks")
    if isinstance(available_benchmarks, list):
        if recommended_type:
            for benchmark in available_benchmarks:
                if not isinstance(benchmark, dict):
                    continue
                if str(benchmark.get("benchmarkType", "")).strip() != recommended_type:
                    continue
                rank_text = _format_percentile_rank(benchmark.get("currentPercentile"))
                if rank_text:
                    return rank_text
        for benchmark in available_benchmarks:
            if not isinstance(benchmark, dict):
                continue
            rank_text = _format_percentile_rank(benchmark.get("currentPercentile"))
            if rank_text:
                return rank_text
    return _extract_percentile_rank_from_payload(payload)


def _resolve_report_date_from_payload(
    payload: dict[str, object],
    business_timezone: timezone | ZoneInfo,
) -> str:
    for field_name in (
        "time",
        "timestamp",
        "date",
        "day",
        "reportDate",
        "report_date",
        "metricTime",
        "metric_time",
        "benchmarkTime",
        "benchmark_time",
        "startTime",
        "start_time",
        "endTime",
        "end_time",
        "bucketStartTime",
        "bucket_start_time",
    ):
        report_date = _parse_report_date_candidate(payload.get(field_name), business_timezone)
        if report_date:
            return report_date
    return ""


def _truncate_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)[:DEBUG_PAYLOAD_MAX_LENGTH]


def _normalize_label(value: str) -> str:
    value = str(value)
    value = ACRONYM_BOUNDARY_PATTERN.sub(r"\1 \2", value)
    value = CAMEL_CASE_BOUNDARY_PATTERN.sub(r"\1 \2", value)
    value = re.sub(r"[^A-Za-z0-9%]+", " ", value)
    return _normalize_space(value).lower().replace("_", " ")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_metric_value(value: str) -> str:
    normalized = _normalize_space(value).strip("|[]{}")
    if normalized.lower().startswith("usd "):
        return "$" + normalized[4:].strip()
    return normalized


def _extract_percentile_rank_from_payload(payload: object) -> str:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _looks_like_percentile_key(key):
                rank_text = _format_percentile_rank(value)
                if rank_text:
                    return rank_text
        for key, value in payload.items():
            if not isinstance(value, dict):
                continue
            if not _looks_like_percentile_container_key(key):
                continue
            rank_text = _extract_percentile_rank_from_payload(value)
            if rank_text:
                return rank_text
    return ""


def _looks_like_percentile_key(raw_key: object) -> bool:
    normalized = _normalize_label(str(raw_key))
    if not normalized:
        return False
    if normalized in PERCENTILE_KEYWORDS:
        return True
    return "percentile" in normalized


def _looks_like_percentile_container_key(raw_key: object) -> bool:
    normalized = _normalize_label(str(raw_key))
    if not normalized:
        return False
    return any(keyword in normalized for keyword in PERCENTILE_CONTAINER_KEYWORDS)


def _format_percentile_rank(value: object) -> str:
    if isinstance(value, str):
        normalized = _normalize_metric_value(value).lower()
        if not normalized:
            return ""
        if re.fullmatch(r"\d+(?:\.\d+)?(?:st|nd|rd|th)", normalized):
            return normalized
        if "percentile" in normalized:
            match = re.search(r"\d+(?:\.\d+)?", normalized)
            if match:
                return _format_percentile_rank(match.group(0))
    numeric = _coerce_numeric(value)
    if numeric is None:
        return ""
    percentile = numeric * 100 if 0.0 <= numeric <= 1.0 else numeric
    percentile = max(0.0, min(100.0, percentile))
    if abs(percentile - round(percentile)) < 0.01:
        return f"{int(round(percentile))}th"
    return f"{percentile:.2f}".rstrip("0").rstrip(".") + "th"


def _parse_report_date_candidate(
    value: object,
    business_timezone: timezone | ZoneInfo,
) -> str:
    if isinstance(value, datetime):
        return value.astimezone(business_timezone).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)):
        epoch_value = float(value)
        if epoch_value > 1_000_000_000_000:
            epoch_value /= 1000
        if epoch_value > 1_000_000_000:
            return datetime.fromtimestamp(epoch_value, tz=timezone.utc).astimezone(business_timezone).date().isoformat()
    if not isinstance(value, str):
        return ""
    raw_value = value.strip()
    if not raw_value:
        return ""
    parsed = _parse_iso_datetime(raw_value)
    if parsed is not None:
        return parsed.astimezone(business_timezone).date().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_value):
        return raw_value
    return ""


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


def _extract_percentile_rank_series(
    values: list[dict[str, object]],
    business_timezone: timezone | ZoneInfo,
) -> dict[str, str]:
    ranks: dict[str, str] = {}
    for series in values:
        for point in series.get("dataPoints", []):
            if not isinstance(point, dict):
                continue
            parsed = _parse_iso_datetime(str(point.get("time", "")))
            rank_text = _extract_percentile_rank_from_payload(point)
            if parsed is None or not rank_text:
                continue
            report_date = _to_business_date_string(parsed, business_timezone)
            ranks[report_date] = rank_text
    return ranks


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


def _format_memory_usage(value: float) -> str:
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))} MB"
    return f"{value:.2f}".rstrip("0").rstrip(".") + " MB"


def _format_frame_rate(value: float) -> str:
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))} FPS"
    return f"{value:.2f}".rstrip("0").rstrip(".") + " FPS"


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


def _resolve_project_query_window(
    project_id: str,
    business_timezone: timezone | ZoneInfo,
) -> tuple[datetime, datetime, date, date] | None:
    business_midnight = _business_midnight_now(business_timezone)
    end_date = (business_midnight - timedelta(days=1)).date()
    start_date = end_date - timedelta(days=9)
    project_start_date = get_project_start_date(project_id)
    if project_start_date is not None and project_start_date > start_date:
        start_date = project_start_date
    if start_date > end_date:
        return None
    start_time = datetime.combine(start_date, datetime.min.time(), tzinfo=business_timezone).astimezone(timezone.utc)
    end_time = business_midnight.astimezone(timezone.utc)
    return start_time, end_time, start_date, end_date


def _aggregate_daily_values(
    datapoints: list[tuple[datetime, float]],
    mode: str,
    business_timezone: timezone | ZoneInfo,
) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for timestamp, value in datapoints:
        grouped.setdefault(_to_business_date_string(timestamp, business_timezone), []).append(value)
    if mode == "average":
        return {report_date: sum(values) / len(values) for report_date, values in grouped.items() if values}
    if mode == "max":
        return {report_date: max(values) for report_date, values in grouped.items() if values}
    if mode == "sum":
        return {report_date: sum(values) for report_date, values in grouped.items() if values}
    return {report_date: values[-1] for report_date, values in grouped.items() if values}


def _extract_cohort_retention_day(series: dict[str, str], cohort_day: int) -> dict[str, str]:
    """从 cohort retention 展平结果中提取指定天数列。"""

    prefix = f"{cohort_day}|"
    extracted: dict[str, str] = {}
    for composite_key, value in series.items():
        if not composite_key.startswith(prefix):
            continue
        extracted[composite_key.split("|", 1)[1]] = value
    return extracted


def _resolve_business_timezone(timezone_name: str) -> timezone | ZoneInfo:
    """解析项目日报使用的业务时区，失败时退回 UTC。"""

    candidate = timezone_name.strip() or "UTC"
    try:
        return ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _to_business_date_string(timestamp: datetime, business_timezone: timezone | ZoneInfo) -> str:
    """将 UTC 时间戳转换为业务时区对应的日期字符串。"""

    return timestamp.astimezone(business_timezone).date().isoformat()


def _filter_metric_series(
    series: dict[str, str],
    field_name: str,
    project_id: str,
    start_date: date,
    end_date: date,
    metadata_by_metric: dict[str, date],
    *,
    source_metric: str,
    cohort_day: int | None = None,
) -> dict[str, str]:
    """按项目起始日和指标成熟日过滤日期序列。"""

    project_start_date = get_project_start_date(project_id)
    minimum_date = project_start_date or start_date
    maximum_date = end_date
    latest_available_date = metadata_by_metric.get(source_metric)
    if latest_available_date is not None and latest_available_date < maximum_date:
        maximum_date = latest_available_date
    if cohort_day is not None:
        maximum_date = maximum_date - timedelta(days=cohort_day)
    elif field_name == "day1_retention":
        maximum_date = maximum_date - timedelta(days=1)
    elif field_name == "day7_retention":
        maximum_date = maximum_date - timedelta(days=7)
    if maximum_date < minimum_date:
        return {}

    filtered: dict[str, str] = {}
    for report_date, value in series.items():
        current_date = date.fromisoformat(report_date)
        if current_date < minimum_date or current_date > maximum_date:
            continue
        filtered[report_date] = value
    return filtered


def _format_series(series: dict[str, float], formatter) -> dict[str, str]:
    return {report_date: formatter(value) for report_date, value in sorted(series.items())}


def _extract_cohort_retention_series(
    values: list[dict[str, object]],
    business_timezone: timezone | ZoneInfo,
) -> dict[str, str]:
    """解析 DailyCohortRetention 的 CohortDay 分桶结果。"""

    series_by_key: dict[str, str] = {}
    for series in values:
        cohort_day = _extract_cohort_day_value(series.get("breakdownValue", []))
        if cohort_day is None:
            continue
        for timestamp, value in _flatten_numeric_datapoints([series]):
            report_date = _to_business_date_string(timestamp, business_timezone)
            series_by_key[f"{cohort_day}|{report_date}"] = _format_ratio(value)
    return series_by_key


def _extract_cohort_retention_rank_series(
    values: list[dict[str, object]],
    business_timezone: timezone | ZoneInfo,
) -> dict[str, str]:
    """解析 DailyCohortRetention 的 CohortDay 分桶百分位结果。"""

    series_by_key: dict[str, str] = {}
    for series in values:
        cohort_day = _extract_cohort_day_value(series.get("breakdownValue", []))
        if cohort_day is None:
            continue
        for point in series.get("dataPoints", []):
            if not isinstance(point, dict):
                continue
            parsed = _parse_iso_datetime(str(point.get("time", "")))
            rank_text = _extract_percentile_rank_from_payload(point)
            if parsed is None or not rank_text:
                continue
            report_date = _to_business_date_string(parsed, business_timezone)
            series_by_key[f"{cohort_day}|{report_date}"] = rank_text
    return series_by_key


def _extract_cohort_day_value(breakdown_values: object) -> int | None:
    """从 CohortDay 的 breakdownValue 中提取天数。"""

    if not isinstance(breakdown_values, list):
        return None
    for item in breakdown_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("dimension", "")).strip() != "CohortDay":
            continue
        raw_value = str(item.get("value", "")).strip()
        if not raw_value:
            return None
        try:
            return int(float(raw_value))
        except ValueError:
            return None
    return None


def _extract_metric_latest_dates(payload: object) -> dict[str, date]:
    """从 metrics/metadata 响应中提取每个指标的最新可用日期。"""

    if not isinstance(payload, dict):
        return {}
    operation = payload.get("operation")
    if not isinstance(operation, dict):
        return {}
    result = operation.get("metricMetadataResult")
    if not isinstance(result, dict):
        return {}
    metadata = result.get("metadata")
    if not isinstance(metadata, list):
        return {}

    latest_dates: dict[str, date] = {}
    for item in metadata:
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric", "")).strip()
        parsed = _parse_iso_datetime(str(item.get("latestAvailableTime", "")))
        if not metric or parsed is None:
            continue
        latest_dates[metric] = parsed.date()
    return latest_dates


def _extract_session_bucket_retention_series(
    values: list[dict[str, object]],
    threshold_seconds: int,
    business_timezone: timezone | ZoneInfo,
) -> dict[str, float]:
    bucket_counts_by_date: dict[str, dict[int, float]] = {}
    for series in values:
        bucket_seconds = _extract_session_bucket_seconds(series.get("breakdownValue", []))
        if bucket_seconds is None:
            continue
        for timestamp, value in _flatten_numeric_datapoints([series]):
            report_date = _to_business_date_string(timestamp, business_timezone)
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


def _extract_breakdown_daily_counts(
    values: list[dict[str, object]],
    expected_value: str,
    business_timezone: timezone | ZoneInfo,
    *,
    aliases: tuple[str, ...] = (),
) -> dict[str, float]:
    expected_values = (expected_value, *aliases)
    counts: dict[str, float] = {}
    for series in values:
        if not any(_contains_breakdown_value(series.get("breakdownValue", []), candidate) for candidate in expected_values):
            continue
        for timestamp, value in _flatten_numeric_datapoints([series]):
            report_date = _to_business_date_string(timestamp, business_timezone)
            counts[report_date] = counts.get(report_date, 0.0) + value
    return counts


def _business_midnight_now(business_timezone: timezone | ZoneInfo) -> datetime:
    now = datetime.now(business_timezone)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
