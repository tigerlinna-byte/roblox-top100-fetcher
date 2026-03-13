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


def _build_html_response(html_text: str) -> Mock:
    response = Mock()
    response.status_code = 200
    response.url = "https://create.roblox.com/dashboard/creations/experiences/9682356542/overview"
    response.text = html_text
    return response


def _wrap_query_result(value: dict | list[dict]) -> dict:
    values = value if isinstance(value, list) else [value]
    return {"operation": {"done": True, "queryResult": {"values": values}}}


class RobloxCreatorMetricsClientTests(unittest.TestCase):
    def test_fetch_project_daily_metrics_extracts_direct_metrics(self) -> None:
        session = Mock()

        def request(method: str, url: str, **kwargs):
            if method == "GET" and "feature-permissions" in url:
                return _build_json_response({"userCanViewAnalyticsForUniverse": True})
            if method == "GET" and "status-config" in url:
                return _build_json_response({"annotationConfigurations": []})
            if method == "POST" and "analytics-query-gateway" in url:
                metric = kwargs["json"]["query"]["metric"]
                if metric == "ConcurrentPlayers":
                    return _build_json_response(
                        _wrap_query_result(
                            {"breakdownValue": [], "dataPoints": [
                                {"time": "2026-03-11T01:00:00Z", "value": 3.2},
                                {"time": "2026-03-11T02:00:00Z", "value": 4.6},
                            ]}
                        )
                    )
                if metric == "PeakConcurrentPlayers":
                    return _build_json_response(
                        _wrap_query_result(
                            {"breakdownValue": [], "dataPoints": [
                                {"time": "2026-03-11T01:00:00Z", "value": 5.1},
                                {"time": "2026-03-11T02:00:00Z", "value": 6.2},
                            ]}
                        )
                    )
                if metric == "AverageSessionLengthMinutes":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 12.5}]})
                    )
                if metric == "D1Retention":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 0.312}]})
                    )
                if metric == "D7Retention":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 0.124}]})
                    )
                if metric == "PayingUsersCVR":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 0.025}]})
                    )
                if metric == "AverageRevenuePerPayingUser":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 8.9}]})
                    )
                if metric == "RFYQualifiedPTR":
                    return _build_json_response(
                        _wrap_query_result({"breakdownValue": [], "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 0.042}]})
                    )
                if metric == "DailyActiveUsers":
                    return _build_json_response(
                        _wrap_query_result(
                            [
                                {
                                    "breakdownValue": [{"dimension": "AcquisitionSource", "value": "HomeRecommendation"}],
                                    "dataPoints": [{"time": "2026-03-11T00:00:00Z", "value": 584}],
                                }
                            ]
                        )
                    )
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            if method == "GET":
                return _build_html_response("<html><body></body></html>")
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

        record = client.fetch_project_daily_metrics()

        self.assertEqual("4", record.average_ccu)
        self.assertEqual("6", record.peak_ccu)
        self.assertEqual("12m 30s", record.average_session_time)
        self.assertEqual("31.2%", record.day1_retention)
        self.assertEqual("12.4%", record.day7_retention)
        self.assertEqual("2.5%", record.payer_conversion_rate)
        self.assertEqual("$8.90", record.arppu)
        self.assertEqual("4.2%", record.qptr)
        self.assertEqual("584", record.home_recommendations)
        self.assertEqual("未获取", record.five_minute_retention)

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
            if method == "GET":
                return _build_html_response("<html><body></body></html>")
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

        record = client.fetch_project_daily_metrics()

        self.assertEqual("3", record.average_ccu)
        self.assertEqual("5", record.peak_ccu)
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
            if method == "POST" and "analytics-query-gateway" in url:
                return _build_json_response(_wrap_query_result({"breakdownValue": [], "dataPoints": []}))
            if method == "GET":
                return _build_html_response("<html><body><div>No metrics</div></body></html>")
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
