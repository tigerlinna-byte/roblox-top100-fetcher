from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from app.config import Config
from app.roblox_creator_metrics_client import RobloxCreatorMetricsClient, RobloxCreatorMetricsClientError


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


class RobloxCreatorMetricsClientTests(unittest.TestCase):
    def test_fetch_project_daily_metrics_extracts_recent_series(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AverageSessionLengthMinutes", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "TotalSessionsEndedInBucket", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyActiveUsers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "ConcurrentPlayers":
                    return _build_json_response(
                        _wrap_query_result(
                            {"breakdownValue": [], "dataPoints": [
                                {"time": "2026-03-10T01:00:00Z", "value": 3.2},
                                {"time": "2026-03-10T02:00:00Z", "value": 4.8},
                                {"time": "2026-03-11T01:00:00Z", "value": 5.2},
                                {"time": "2026-03-11T02:00:00Z", "value": 6.8},
                            ]}
                        )
                    )
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(
                        _wrap_query_result(
                            {"breakdownValue": [], "dataPoints": [
                                {"time": "2026-03-10T01:00:00Z", "value": 7.1},
                                {"time": "2026-03-10T02:00:00Z", "value": 8.2},
                                {"time": "2026-03-11T01:00:00Z", "value": 9.5},
                                {"time": "2026-03-11T02:00:00Z", "value": 10.1},
                            ]}
                        )
                    )
                if metric == "AverageSessionLengthMinutes":
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
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
                if metric == "AverageRevenuePerPayingUser":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
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
                if metric == "DailyActiveUsers":
                    return _build_json_response(
                        _wrap_query_result(
                            [
                                {
                                    "breakdownValue": [{"dimension": "AcquisitionSource", "value": "HomeRecommendation"}],
                                    "dataPoints": [
                                        {"time": "2026-03-10T00:00:00Z", "value": 584},
                                        {"time": "2026-03-11T00:00:00Z", "value": 610},
                                    ],
                                }
                            ]
                        )
                    )
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
        self.assertEqual("6", record_map["2026-03-11"].average_ccu)
        self.assertEqual("10", record_map["2026-03-11"].peak_ccu)
        self.assertEqual("15m 0s", record_map["2026-03-11"].average_session_time)
        self.assertEqual("", record_map["2026-03-11"].day1_retention)
        self.assertEqual("50%", record_map["2026-03-11"].five_minute_retention)
        self.assertEqual("610", record_map["2026-03-11"].home_recommendations)
        self.assertEqual("6.77%", record_map["2026-03-10"].day1_retention)
        self.assertEqual("", record_map["2026-03-10"].day7_retention)
        self.assertEqual("7.58%", record_map["2026-03-09"].day1_retention)
        self.assertNotIn("2026-03-04", record_map)
        self.assertNotIn("2026-03-13", record_map)

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
            if method == "POST" and "metrics/metadata" in url:
                return _build_json_response({
                    "operation": {
                        "done": True,
                        "metricMetadataResult": {
                            "metadata": [
                                {"metric": "AverageSessionLengthMinutes", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "ConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "PeakConcurrentPlayers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyCohortRetention", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "TotalSessionsEndedInBucket", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                                {"metric": "DailyActiveUsers", "latestAvailableTime": "2026-03-11T00:00:00Z"},
                            ]
                        },
                    }
                })
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                token = kwargs["headers"].get("x-csrf-token", "")
                if metric == "ConcurrentPlayers" and not token:
                    return csrf_failed
                if metric == "ConcurrentPlayers":
                    return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 3.0}]}))
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

        self.assertEqual("3", records[0].average_ccu)
        self.assertEqual("5", records[0].peak_ccu)
        self.assertEqual("token-123", client._csrf_token)

    def test_fetch_project_daily_metrics_writes_debug_snapshot_when_core_metrics_missing(self) -> None:
        session = Mock()
        output_dir = Path(".test-output")
        output_dir.mkdir(parents=True, exist_ok=True)
        debug_path = output_dir / "creator_overview_debug.json"
        if debug_path.exists():
            debug_path.unlink()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and ("feature-permissions" in url or "status-config" in url):
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

        self.assertTrue(debug_path.exists())


if __name__ == "__main__":
    unittest.main()
