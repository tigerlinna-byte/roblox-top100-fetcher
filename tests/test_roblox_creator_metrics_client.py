from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

from app.config import Config
from app.project_metrics_models import get_project_required_fields
from app.roblox_creator_metrics_client import (
    RobloxCreatorMetricsClient,
    RobloxCreatorMetricsClientError,
    resolve_project_metrics_query_date_bounds,
)


def _build_json_response(payload: dict, *, status_code: int = 200, headers: dict[str, str] | None = None) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = payload
    response.text = "{}"
    response.url = "https://create.roblox.com/dashboard/creations/experiences/9682356542/overview"
    return response


def _wrap_query_result(value: dict | list[dict]) -> dict:
    values = value if isinstance(value, list) else [value]
    return {"operation": {"done": True, "queryResult": {"values": values}}}


def _extract_metric_query(url: str) -> str:
    query = parse_qs(urlparse(url).query)
    return query.get("metric", [""])[0]


def _build_benchmark_scorecard_payload(
    metric_time: str,
    current_percentile: int,
    *,
    current_value: float = 0.0,
) -> dict:
    return {
        "metricTime": metric_time,
        "currentValue": current_value,
        "currentPercentile": current_percentile,
        "availableBenchmarks": [],
        "recommendedType": "",
        "benchmarkTime": metric_time,
        "metricCurrentValue": current_value,
    }


class RobloxCreatorMetricsClientTests(unittest.TestCase):
    def test_get_project_required_fields_returns_project_specific_override(self) -> None:
        self.assertEqual(("peak_ccu",), get_project_required_fields("9682356542"))
        self.assertEqual((), get_project_required_fields("9707829514"))

    def test_resolve_project_metrics_query_date_bounds_keeps_full_project_backfill_window(self) -> None:
        mocked_midnight = datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)

        with patch("app.roblox_creator_metrics_client._business_midnight_now", return_value=mocked_midnight):
            bounds = resolve_project_metrics_query_date_bounds("9682356542", "UTC")

        self.assertEqual((date(2026, 3, 9), date(2026, 5, 4)), bounds)

    def test_resolve_project_metrics_query_date_bounds_keeps_full_backfill_for_non_required_peak_ccu(self) -> None:
        mocked_midnight = datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)

        with patch("app.roblox_creator_metrics_client._business_midnight_now", return_value=mocked_midnight):
            bounds = resolve_project_metrics_query_date_bounds("9707829514", "UTC")

        self.assertEqual((date(2026, 3, 17), date(2026, 5, 4)), bounds)

    def test_resolve_project_metrics_query_date_bounds_uses_troll_ur_friends_start_date(self) -> None:
        mocked_midnight = datetime(2026, 6, 3, 0, 0, tzinfo=timezone.utc)

        with patch("app.roblox_creator_metrics_client._business_midnight_now", return_value=mocked_midnight):
            bounds = resolve_project_metrics_query_date_bounds("10170801715", "UTC")

        self.assertEqual((date(2026, 5, 31), date(2026, 6, 2)), bounds)

    def test_fetch_project_revenue_series_uses_latest_available_revenue_month(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "Revenue", "latestAvailableTime": "2026-05-04T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                self.assertEqual("Revenue", metric)
                return _build_json_response(
                    _wrap_query_result(
                        {"breakdownValue": [], "dataPoints": [
                            {"time": "2026-05-01T00:00:00Z", "value": 1000},
                            {"time": "2026-05-02T00:00:00Z", "value": 2000},
                            {"time": "2026-05-03T00:00:00Z", "value": 3000},
                            {"time": "2026-05-04T00:00:00Z", "value": 4000},
                        ]}
                    )
                )
            raise AssertionError(f"Unexpected request {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="cookie",
                feishu_timezone="UTC",
            ),
            session=session,
        )
        mocked_midnight = datetime(2026, 5, 5, 0, 0, tzinfo=timezone.utc)

        with patch("app.roblox_creator_metrics_client._business_midnight_now", return_value=mocked_midnight):
            series = client.fetch_project_revenue_series(
                "https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                minimum_start_date=date(2026, 5, 1),
            )

        self.assertEqual("Revenue", series.metric)
        self.assertEqual(
            {
                "2026-05-01": 1000,
                "2026-05-02": 2000,
                "2026-05-03": 3000,
                "2026-05-04": 4000,
            },
            series.values,
        )

    def test_fetch_project_daily_metrics_extracts_recent_series(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                metric = _extract_metric_query(url)
                scorecards = {
                    "L7AveragePlayTimeMinutesPerDAU": _build_benchmark_scorecard_payload("2026-03-11T00:00:00Z", 82, current_value=15.0),
                    "L7AverageForwardD1Retention": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 72, current_value=0.0677),
                    "L7AverageForwardD7Retention": _build_benchmark_scorecard_payload("2026-03-05T00:00:00Z", 63, current_value=0.0070),
                    "L7AveragePayingUsersCVR": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 58, current_value=0.025),
                    "L7AverageRevenuePerPayingUser": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 77, current_value=8.9),
                }
                return _build_json_response(scorecards.get(metric, {}))
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AverageSessionLengthMinutes", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "TotalSessionsEndedInBucket", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "UniqueUsersWithImpressions", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ClientCrashRate15m", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ClientMemoryUsagePercentageAvg", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ClientFpsAvg", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ServerCrashCount", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "MemoryUsageAvg", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ServerFrameRateAvg", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(
                        _wrap_query_result(
                            {"breakdownValue": [], "dataPoints": [
                                {"time": "2026-03-09T00:00:00Z", "value": 7.4},
                                {"time": "2026-03-10T00:00:00Z", "value": 8.2},
                                {"time": "2026-03-11T00:00:00Z", "value": 10.1},
                            ]}
                        )
                    )
                if metric == "AveragePlayTimeMinutesPerDAU":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [
                            {"time": "2026-03-10T00:00:00Z", "value": 12.5},
                            {"time": "2026-03-11T00:00:00Z", "value": 15.0},
                            {"time": "2026-03-12T00:00:00Z", "value": 18.0},
                        ]})
                    )
                if metric == "DailyCohortRetention":
                    return _build_json_response(
                        _wrap_query_result([
                            {
                                "breakdownValue": [{"dimension": "CohortDay", "value": "1"}],
                                "dataPoints": [
                                    {"time": "2026-03-09T00:00:00Z", "value": 0.0758},
                                    {"time": "2026-03-10T00:00:00Z", "value": 0.0677},
                                    {"time": "2026-03-11T00:00:00Z", "value": 0.0811},
                                ],
                            },
                            {
                                "breakdownValue": [{"dimension": "CohortDay", "value": "7"}],
                                "dataPoints": [
                                    {"time": "2026-03-04T00:00:00Z", "value": 0.0061},
                                    {"time": "2026-03-05T00:00:00Z", "value": 0.0070},
                                ],
                            },
                        ])
                    )
                if metric == "PayingUsersCVR":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 0.025},
                        {"time": "2026-03-11T00:00:00Z", "value": 0.03},
                    ]}))
                if metric == "AverageRevenuePerPayingUser":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 8.9},
                        {"time": "2026-03-11T00:00:00Z", "value": 9.3},
                    ]}))
                if metric == "RFYQualifiedPTR":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
                if metric == "TotalSessionsEndedInBucket":
                    return _build_json_response(
                        _wrap_query_result(
                            [
                                {
                                    "breakdownValue": [{"dimension": "SessionTimeBucket", "value": "0"}],
                                    "dataPoints": [
                                        {"time": "2026-03-10T00:00:00Z", "value": 1000},
                                        {"time": "2026-03-11T00:00:00Z", "value": 900},
                                    ],
                                },
                                {
                                    "breakdownValue": [{"dimension": "SessionTimeBucket", "value": "300"}],
                                    "dataPoints": [
                                        {"time": "2026-03-10T00:00:00Z", "value": 420},
                                        {"time": "2026-03-11T00:00:00Z", "value": 450},
                                    ],
                                },
                            ]
                        )
                    )
                if metric == "UniqueUsersWithImpressions":
                    return _build_json_response(
                        _wrap_query_result(
                            [
                                {
                                    "breakdownValue": [{"dimension": "AcquisitionSource", "value": "Home Recommendation"}],
                                    "dataPoints": [
                                        {"time": "2026-03-10T00:00:00Z", "value": 584},
                                        {"time": "2026-03-11T00:00:00Z", "value": 610},
                                    ],
                                }
                            ]
                        )
                    )
                if metric == "ClientCrashRate15m":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 0.0012},
                        {"time": "2026-03-11T00:00:00Z", "value": 0.0015},
                    ]}))
                if metric == "ClientMemoryUsagePercentageAvg":
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "Platform", "value": "Tablet"}],
                            "dataPoints": [
                                {"time": "2026-03-10T00:00:00Z", "value": 0.4},
                                {"time": "2026-03-11T00:00:00Z", "value": 0.42},
                                {"time": "2026-03-11T12:00:00Z", "value": 0.44},
                            ],
                        },
                        {
                            "breakdownValue": [{"dimension": "Platform", "value": "Computer"}],
                            "dataPoints": [
                                {"time": "2026-03-11T00:00:00Z", "value": 55},
                            ],
                        },
                        {
                            "breakdownValue": [{"dimension": "Platform", "value": "Phone"}],
                            "dataPoints": [
                                {"time": "2026-03-11T00:00:00Z", "value": 0.61},
                            ],
                        },
                    ]))
                if metric == "ClientFpsAvg":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 58.25},
                        {"time": "2026-03-11T00:00:00Z", "value": 59.5},
                    ]}))
                if metric == "ServerCrashCount":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 1},
                        {"time": "2026-03-11T00:00:00Z", "value": 2},
                        {"time": "2026-03-11T12:00:00Z", "value": 3},
                    ]}))
                if metric == "MemoryUsageAvg":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 500},
                        {"time": "2026-03-11T00:00:00Z", "value": 512},
                        {"time": "2026-03-11T12:00:00Z", "value": 514},
                    ]}))
                if metric == "ServerFrameRateAvg":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 60.0},
                        {"time": "2026-03-11T00:00:00Z", "value": 59.75},
                    ]}))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        records = client.fetch_project_daily_metrics()

        self.assertEqual(["2026-03-11", "2026-03-10", "2026-03-09"], [record.report_date for record in records])
        record_map = {record.report_date: record for record in records}
        self.assertEqual("10", record_map["2026-03-11"].peak_ccu)
        self.assertEqual("15m 0s", record_map["2026-03-11"].average_session_time)
        self.assertEqual("82th", record_map["2026-03-11"].average_session_time_rank)
        self.assertEqual("", record_map["2026-03-11"].day1_retention)
        self.assertEqual("50%", record_map["2026-03-11"].five_minute_retention)
        self.assertEqual("610", record_map["2026-03-11"].home_recommendations)
        self.assertEqual("0.15%", record_map["2026-03-11"].client_crash_rate)
        self.assertEqual("43%", record_map["2026-03-11"].tablet_memory_percentage)
        self.assertEqual("55%", record_map["2026-03-11"].pc_memory_percentage)
        self.assertEqual("61%", record_map["2026-03-11"].phone_memory_percentage)
        self.assertEqual("59.5 FPS", record_map["2026-03-11"].client_frame_rate)
        self.assertEqual("5", record_map["2026-03-11"].server_crashes)
        self.assertEqual("513 MB", record_map["2026-03-11"].server_memory)
        self.assertEqual("59.75 FPS", record_map["2026-03-11"].server_frame_rate)
        self.assertEqual("6.77%", record_map["2026-03-10"].day1_retention)
        self.assertEqual("72th", record_map["2026-03-10"].day1_retention_rank)
        self.assertEqual("58th", record_map["2026-03-10"].payer_conversion_rate_rank)
        self.assertEqual("77th", record_map["2026-03-10"].arppu_rank)
        self.assertEqual("", record_map["2026-03-10"].day7_retention)
        self.assertEqual("7.58%", record_map["2026-03-09"].day1_retention)
        self.assertEqual("", record_map["2026-03-09"].day7_retention_rank)
        self.assertNotIn("2026-03-05", record_map)
        self.assertNotIn("2026-03-04", record_map)
        self.assertNotIn("2026-03-13", record_map)
        memory_requests = [
            json_payload["query"]
            for call in session.request.call_args_list
            if isinstance((json_payload := call.kwargs.get("json")), dict)
            and json_payload.get("query", {}).get("metric") == "ClientMemoryUsagePercentageAvg"
        ]
        self.assertTrue(memory_requests)
        self.assertTrue(all(request["breakdown"] == [{"dimensions": ["Platform"]}] for request in memory_requests))
        server_memory_requests = [
            json_payload["query"]
            for call in session.request.call_args_list
            if isinstance((json_payload := call.kwargs.get("json")), dict)
            and json_payload.get("query", {}).get("metric") == "MemoryUsageAvg"
        ]
        self.assertTrue(server_memory_requests)
        self.assertTrue(all(request["breakdown"] == [] for request in server_memory_requests))

    def test_fetch_project_daily_metrics_uses_benchmark_scorecard_for_ranks(self) -> None:
        session = Mock()
        overview_url = "https://create.roblox.com/dashboard/creations/experiences/1234567890/overview"
        mocked_window = (
            datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 18, 0, 0, tzinfo=timezone.utc),
            date(2026, 3, 1),
            date(2026, 3, 17),
        )

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                metric = _extract_metric_query(url)
                scorecards = {
                    "L7AveragePlayTimeMinutesPerDAU": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 82, current_value=12.5),
                    "L7AverageForwardD1Retention": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 71, current_value=0.0677),
                    "L7AverageForwardD7Retention": _build_benchmark_scorecard_payload("2026-03-05T00:00:00Z", 63, current_value=0.0070),
                    "L7AveragePayingUsersCVR": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 58, current_value=0.025),
                    "L7AverageRevenuePerPayingUser": _build_benchmark_scorecard_payload("2026-03-10T00:00:00Z", 76, current_value=8.9),
                }
                return _build_json_response(scorecards.get(metric, {}))
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-17T00:00:00Z"},
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-17T00:00:00Z"},
                                {"metric": "PayingUsersCVR", "latestAvailableTime": "2026-03-17T00:00:00Z"},
                                {"metric": "AverageRevenuePerPayingUser", "latestAvailableTime": "2026-03-17T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-17T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-05T00:00:00Z", "value": 7.6},
                        {"time": "2026-03-10T00:00:00Z", "value": 11.1},
                    ]}))
                if metric == "AveragePlayTimeMinutesPerDAU":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 12.5},
                    ]}))
                if metric == "PayingUsersCVR":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 0.025},
                    ]}))
                if metric == "AverageRevenuePerPayingUser":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 8.9},
                    ]}))
                if metric == "DailyCohortRetention":
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "CohortDay", "value": "1"}],
                            "dataPoints": [{"time": "2026-03-10T00:00:00Z", "value": 0.0677}],
                        },
                        {
                            "breakdownValue": [{"dimension": "CohortDay", "value": "7"}],
                            "dataPoints": [{"time": "2026-03-05T00:00:00Z", "value": 0.0070}],
                        },
                    ]))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url=overview_url,
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        with patch("app.roblox_creator_metrics_client._resolve_project_query_window", return_value=mocked_window):
            records = client.fetch_project_daily_metrics()
        record_map = {record.report_date: record for record in records}

        self.assertEqual("82th", record_map["2026-03-10"].average_session_time_rank)
        self.assertEqual("71th", record_map["2026-03-10"].day1_retention_rank)
        self.assertEqual("63th", record_map["2026-03-05"].day7_retention_rank)
        self.assertEqual("58th", record_map["2026-03-10"].payer_conversion_rate_rank)
        self.assertEqual("76th", record_map["2026-03-10"].arppu_rank)

    def test_fetch_project_daily_metrics_refreshes_xcsrf_token(self) -> None:
        session = Mock()
        csrf_failed = _build_json_response(
            {"errors": [{"message": "XSRF token invalid"}]},
            status_code=403,
            headers={"x-csrf-token": "token-123"},
        )

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AverageSessionLengthMinutes", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "TotalSessionsEndedInBucket", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "UniqueUsersWithImpressions", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ClientCrashRate15m", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                token = kwargs["headers"].get("x-csrf-token", "")
                if metric == "PeakConcurrentPlayers" and not token:
                    return csrf_failed
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 5.0}]}))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        records = client.fetch_project_daily_metrics()

        self.assertEqual("5", records[0].peak_ccu)
        self.assertEqual("token-123", client._csrf_token)

    def test_fetch_project_daily_metrics_polls_async_query_results(self) -> None:
        session = Mock()
        query_counts: dict[str, int] = {}

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-12T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-12T00:00:00Z"},
                                {"metric": "UniqueUsersWithImpressions", "latestAvailableTime": "2026-03-12T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                query_counts[metric] = query_counts.get(metric, 0) + 1
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 10.5},
                        {"time": "2026-03-12T00:00:00Z", "value": 12.2},
                    ]}))
                if metric == "DailyCohortRetention":
                    if query_counts[metric] == 1:
                        return _build_json_response({"operation": {"path": "async-retention", "done": False}})
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "CohortDay", "value": "1"}],
                            "dataPoints": [{"time": "2026-03-10T00:00:00Z", "value": 0.0677}],
                        }
                    ]))
                if metric == "UniqueUsersWithImpressions":
                    if query_counts[metric] == 1:
                        return _build_json_response({"operation": {"path": "async-home", "done": False}})
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "AcquisitionSource", "value": "HomeRecommendation"}],
                            "dataPoints": [{"time": "2026-03-10T00:00:00Z", "value": 584}],
                        }
                    ]))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=2,
                retry_backoff_seconds=0,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        records = client.fetch_project_daily_metrics()
        record_map = {record.report_date: record for record in records}

        self.assertEqual("12", record_map["2026-03-12"].peak_ccu)
        self.assertEqual("6.77%", record_map["2026-03-10"].day1_retention)
        self.assertEqual("584", record_map["2026-03-10"].home_recommendations)
        self.assertEqual(2, query_counts["DailyCohortRetention"])
        self.assertEqual(2, query_counts["UniqueUsersWithImpressions"])

    def test_fetch_project_daily_metrics_writes_debug_snapshot_when_core_metrics_missing(self) -> None:
        session = Mock()
        output_dir = Path(".test-output")
        output_dir.mkdir(parents=True, exist_ok=True)
        for debug_path in output_dir.glob("creator_overview_debug*.json"):
            debug_path.unlink()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and ("feature-permissions" in url or "status-config" in url):
                return _build_json_response({})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({"operation": {"done": True, "metricMetadataResult": {"metadata": []}}})
            if method == "POST" and "analytics-query-gateway" in url:
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
                output_dir=str(output_dir),
            ),
            session=session,
        )

        with self.assertRaisesRegex(RobloxCreatorMetricsClientError, "核心指标"):
            client.fetch_project_daily_metrics()

        debug_path = output_dir / "creator_overview_debug_9682356542.json"
        self.assertTrue(debug_path.exists())
        payload = json.loads(debug_path.read_text(encoding="utf-8"))
        self.assertEqual("9682356542", payload["project_id"])

    def test_fetch_project_daily_metrics_rejects_dates_missing_required_peak_ccu(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and ("feature-permissions" in url or "status-config" in url):
                return _build_json_response({})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-10T00:00:00Z"},
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 8.2},
                    ]}))
                if metric == "AveragePlayTimeMinutesPerDAU":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 12.5},
                        {"time": "2026-03-11T00:00:00Z", "value": 15.0},
                    ]}))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        with self.assertRaisesRegex(RobloxCreatorMetricsClientError, "2026-03-11: peak_ccu"):
            client.fetch_project_daily_metrics()

    def test_fetch_project_daily_metrics_skips_peak_ccu_when_field_plan_does_not_request_it(self) -> None:
        session = Mock()
        queried_metrics: list[str] = []

        def request(method: str, url: str, **kwargs):
            if method == "GET" and ("feature-permissions" in url or "status-config" in url):
                return _build_json_response({})
            if method == "GET" and "benchmark-scorecard" in url:
                raise AssertionError("benchmark rank should not be queried")
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-10T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                queried_metrics.append(metric)
                if metric == "PeakConcurrentPlayers":
                    raise AssertionError("peak_ccu should not be queried")
                if metric == "AveragePlayTimeMinutesPerDAU":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-10T00:00:00Z", "value": 12.5},
                    ]}))
                raise AssertionError(f"unexpected metric query: {metric}")
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="UTC",
            ),
            session=session,
        )

        records = client.fetch_project_daily_metrics(
            report_dates=[date(2026, 3, 10)],
            requested_fields_by_date={date(2026, 3, 10): ("average_session_time",)},
        )

        self.assertEqual(["AveragePlayTimeMinutesPerDAU"], queried_metrics)
        self.assertEqual(1, len(records))
        self.assertEqual("2026-03-10", records[0].report_date)
        self.assertEqual("", records[0].peak_ccu)
        self.assertEqual("12m 30s", records[0].average_session_time)

    def test_fetch_project_daily_metrics_allows_project_without_required_peak_ccu(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AveragePlayTimeMinutesPerDAU", "latestAvailableTime": "2026-03-30T00:00:00Z"},
                                {"metric": "PayingUsersCVR", "latestAvailableTime": "2026-03-30T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-30T00:00:00Z"},
                                {"metric": "TotalSessionsEndedInBucket", "latestAvailableTime": "2026-03-30T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response({"operation": {"done": True, "queryResult": {"values": []}}})
                if metric == "AveragePlayTimeMinutesPerDAU":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-29T00:00:00Z", "value": 8.4},
                        {"time": "2026-03-30T00:00:00Z", "value": 5.2},
                    ]}))
                if metric == "PayingUsersCVR":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [
                        {"time": "2026-03-29T00:00:00Z", "value": 0.1428571492433548},
                        {"time": "2026-03-30T00:00:00Z", "value": 0.0},
                    ]}))
                if metric == "DailyCohortRetention":
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "CohortDay", "value": "1"}],
                            "dataPoints": [
                                {"time": "2026-03-28T00:00:00Z", "value": 0.1818181872367859},
                                {"time": "2026-03-29T00:00:00Z", "value": 0.1428571492433548},
                            ],
                        }
                    ]))
                if metric == "TotalSessionsEndedInBucket":
                    return _build_json_response(_wrap_query_result([
                        {
                            "breakdownValue": [{"dimension": "SessionTimeBucket", "value": "0"}],
                            "dataPoints": [
                                {"time": "2026-03-29T00:00:00Z", "value": 14},
                                {"time": "2026-03-30T00:00:00Z", "value": 7},
                            ],
                        },
                        {
                            "breakdownValue": [{"dimension": "SessionTimeBucket", "value": "300"}],
                            "dataPoints": [
                                {"time": "2026-03-29T00:00:00Z", "value": 4},
                                {"time": "2026-03-30T00:00:00Z", "value": 2},
                            ],
                        },
                    ]))
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
            ),
            session=session,
        )

        records = client.fetch_project_daily_metrics()

        self.assertEqual(["2026-03-30", "2026-03-29", "2026-03-28"], [record.report_date for record in records])
        self.assertEqual("", records[0].peak_ccu)
        self.assertEqual("5m 12s", records[0].average_session_time)
        self.assertEqual("0%", records[0].payer_conversion_rate)

    def test_fetch_project_daily_metrics_splits_large_peak_ccu_backfill_windows(self) -> None:
        session = Mock()
        peak_windows: list[tuple[datetime, datetime]] = []

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "GET" and "benchmark-scorecard" in url:
                return _build_json_response({})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({"operation": {"done": True, "metricMetadataResult": {"metadata": []}}})
            if method == "POST" and "analytics-query-gateway" in url:
                query = kwargs["json"]["query"]
                metric = query["metric"]
                if metric != "PeakConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))

                start_time = datetime.fromisoformat(query["startTime"].replace("Z", "+00:00"))
                end_time = datetime.fromisoformat(query["endTime"].replace("Z", "+00:00"))
                peak_windows.append((start_time, end_time))
                if end_time - start_time > timedelta(days=14):
                    return _build_json_response({"errors": [{"message": "window too large"}]}, status_code=500)

                data_points = []
                if start_time.date() <= date(2026, 5, 4) < end_time.date():
                    data_points.append({"time": "2026-05-04T00:00:00Z", "value": 569})
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": data_points}))
            raise AssertionError(f"unexpected request: {method} {url}")

        session.request.side_effect = request
        client = RobloxCreatorMetricsClient(
            Config(
                output_dir=".test-output",
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                retry_backoff_seconds=0,
                feishu_timezone="UTC",
            ),
            session=session,
        )
        report_dates = [date(2026, 3, 17) + timedelta(days=index) for index in range(49)]

        records = client.fetch_project_daily_metrics(report_dates=report_dates)

        self.assertTrue(peak_windows)
        self.assertTrue(all(end_time - start_time <= timedelta(days=14) for start_time, end_time in peak_windows))
        record_map = {record.report_date: record for record in records}
        self.assertEqual("569", record_map["2026-05-04"].peak_ccu)

    def test_request_json_preserves_retry_cause(self) -> None:
        session = Mock()
        session.request.return_value = _build_json_response({"errors": [{"message": "server failed"}]}, status_code=500)
        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                retry_backoff_seconds=0,
            ),
            session=session,
        )

        with self.assertRaisesRegex(RobloxCreatorMetricsClientError, "HTTP 500"):
            client._request_json("GET", "https://apis.roblox.com/failing", json_body=None)


if __name__ == "__main__":
    unittest.main()
