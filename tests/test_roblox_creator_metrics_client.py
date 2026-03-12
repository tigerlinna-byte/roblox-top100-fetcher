from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock

from app.config import Config
from app.roblox_creator_metrics_client import RobloxCreatorMetricsClient


def _build_gateway_response(payload: dict) -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = payload
    return response


def _build_html_response(html_text: str) -> Mock:
    response = Mock()
    response.status_code = 200
    response.url = "https://create.roblox.com/dashboard/creations/experiences/9682356542/overview"
    response.text = html_text
    return response


class RobloxCreatorMetricsClientTests(unittest.TestCase):
    def test_fetch_project_daily_metrics_extracts_visible_text_metrics(self) -> None:
        session = Mock()
        gateway_response = _build_gateway_response(
            {
                "cards": [
                    {"label": "Average CCU", "value": "1,234"},
                    {"label": "Peak CCU", "value": "2,345"},
                    {"label": "Average Session Time", "value": "18m 30s"},
                    {"label": "Day 1 Retention", "value": "31%"},
                    {"label": "Day 7 Retention", "value": "12%"},
                    {"label": "Payer Conversion Rate", "value": "2.5%"},
                    {"label": "ARPPU", "value": "$8.90"},
                    {"label": "QPTR", "value": "4.2"},
                    {"label": "5 Minute Retention", "value": "40%"},
                    {"label": "Home Recommendations", "value": "98"},
                ]
            }
        )
        session.request.side_effect = [gateway_response]

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

        self.assertEqual("1,234", record.average_ccu)
        self.assertEqual("2,345", record.peak_ccu)
        self.assertEqual("18m 30s", record.average_session_time)
        self.assertEqual("31%", record.day1_retention)
        self.assertEqual("12%", record.day7_retention)
        self.assertEqual("2.5%", record.payer_conversion_rate)
        self.assertEqual("$8.90", record.arppu)
        self.assertEqual("4.2", record.qptr)
        self.assertEqual("40%", record.five_minute_retention)
        self.assertEqual("98", record.home_recommendations)
        self.assertEqual("9682356542", record.project_id)

    def test_fetch_project_daily_metrics_extracts_inline_json_metrics(self) -> None:
        session = Mock()
        gateway_response = _build_gateway_response(
            {
                "cards": [
                    {"label": "Average CCU", "formattedValue": "1,234"},
                    {"label": "Peak CCU", "formattedValue": "2,345"},
                    {"label": "Average Session Time", "formattedValue": "18m 30s"},
                    {"label": "Day 1 Retention", "formattedValue": "31%"},
                    {"label": "Day 7 Retention", "formattedValue": "12%"},
                    {"label": "Payer Conversion Rate", "formattedValue": "2.5%"},
                    {"label": "ARPPU", "formattedValue": "$8.90"},
                    {"label": "QPTR", "formattedValue": "4.2"},
                    {"label": "5 Minute Retention", "formattedValue": "40%"},
                    {"label": "Home Recommendations", "formattedValue": "98"},
                ]
            }
        )
        session.request.side_effect = [gateway_response]

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

        self.assertEqual("1,234", record.average_ccu)
        self.assertEqual("98", record.home_recommendations)

    def test_fetch_project_daily_metrics_falls_back_to_html_when_gateway_metrics_incomplete(self) -> None:
        session = Mock()
        gateway_response = _build_gateway_response({"cards": [{"label": "Average CCU", "value": "1,234"}]})
        html_response = _build_html_response(
            """
            <html>
              <body>
                <div>Peak CCU</div><div>2,345</div>
                <div>Average Session Time</div><div>18m 30s</div>
                <div>Day 1 Retention</div><div>31%</div>
                <div>Day 7 Retention</div><div>12%</div>
                <div>Payer Conversion Rate</div><div>2.5%</div>
                <div>ARPPU</div><div>$8.90</div>
                <div>QPTR</div><div>4.2</div>
                <div>5 Minute Retention</div><div>40%</div>
                <div>Home Recommendations</div><div>98</div>
              </body>
            </html>
            """
        )
        session.request.side_effect = [gateway_response, gateway_response, gateway_response, html_response]

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

        self.assertEqual("1,234", record.average_ccu)
        self.assertEqual("2,345", record.peak_ccu)
        self.assertEqual("$8.90", record.arppu)
        self.assertEqual("4.2", record.qptr)
        self.assertEqual("98", record.home_recommendations)

    def test_fetch_project_daily_metrics_extracts_script_assignment_metrics(self) -> None:
        session = Mock()
        gateway_response = _build_gateway_response(
            {
                "cards": [
                    {"label": "Average CCU", "value": "1,234"},
                    {"label": "Peak CCU", "value": "2,345"},
                    {"label": "Average Session Time", "value": "18m 30s"},
                    {"label": "Day 1 Retention", "value": "31%"},
                    {"label": "Day 7 Retention", "value": "12%"},
                    {"label": "Payer Conversion Rate", "value": "2.5%"},
                    {"label": "ARPPU", "value": "$8.90"},
                    {"label": "QTPR", "value": "4.2"},
                    {"label": "5 Minute Retention", "value": "40%"},
                    {"label": "Home Recommendation Count", "value": "98"},
                ]
            }
        )
        session.request.side_effect = [gateway_response]

        client = RobloxCreatorMetricsClient(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_cookie="_|WARNING:-DO-NOT-SHARE-THIS.",
                retry_max_attempts=1,
                feishu_timezone="Asia/Shanghai",
                output_dir=".test-output",
            ),
            session=session,
        )

        record = client.fetch_project_daily_metrics()

        self.assertEqual("1,234", record.average_ccu)
        self.assertEqual("4.2", record.qptr)
        self.assertEqual("98", record.home_recommendations)

    def test_fetch_project_daily_metrics_writes_debug_snapshot_when_metrics_missing(self) -> None:
        session = Mock()
        gateway_response = _build_gateway_response({"cards": []})
        html_response = _build_html_response("<html><body><div>No metrics</div></body></html>")
        session.request.side_effect = [gateway_response, gateway_response, gateway_response, html_response]

        output_dir = Path(".test-output")
        output_dir.mkdir(parents=True, exist_ok=True)
        debug_path = output_dir / "creator_overview_debug.json"
        if debug_path.exists():
            debug_path.unlink()

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

        with self.assertRaisesRegex(Exception, "creator_overview_debug.json"):
            client.fetch_project_daily_metrics()

        self.assertTrue(debug_path.exists())


if __name__ == "__main__":
    unittest.main()
