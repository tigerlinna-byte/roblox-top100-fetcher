from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.main import (
    ProjectMetricsFetchFailure,
    ProjectMetricsReportPayload,
    _fetch_report_payload,
    _notify_success,
)
from app.models import GameRecord
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.roblox_creator_metrics_client import RobloxCreatorMetricsClientError


class MainTests(unittest.TestCase):
    @patch("app.main._sync_top_trending_sheet")
    @patch("app.main.FeishuClient")
    def test_top_trending_success_sends_briefing_then_sheet_url(self, feishu_client_cls, sync_sheet) -> None:
        cfg = Config(run_report_mode="top_trending_sheet")
        report_payload = {
            "top_trending_v4": [
                GameRecord(
                    rank=1,
                    place_id=101,
                    name="Game A",
                    playing=1000,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-03-10T00:00:00Z",
                )
            ],
            "up_and_coming_v4": [],
            "top_playing_now": [],
        }
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client
        sync_sheet.return_value.url = "https://feishu.cn/sheets/test"

        _notify_success(cfg, report_payload)

        feishu_client.send_group_card.assert_called_once()
        self.assertEqual(1, feishu_client.send_group_markdown.call_count)
        briefing_card = feishu_client.send_group_card.call_args.args[0]
        url_text = feishu_client.send_group_markdown.call_args.args[0]
        self.assertEqual("今日关注（2026-03-14）", briefing_card["header"]["title"]["content"])
        self.assertEqual("https://feishu.cn/sheets/test", url_text)

    @patch("app.main._sync_project_metrics_sheet")
    @patch("app.main.FeishuClient")
    def test_project_metrics_success_sends_each_project_sheet_url(self, feishu_client_cls, sync_sheet) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
        )
        report_payload = ProjectMetricsReportPayload(
            records_by_project_id={
                "9682356542": [
                    ProjectDailyMetricsRecord(
                        report_date="2026-03-18",
                        peak_ccu="100",
                        average_session_time="10m",
                        day1_retention="10%",
                        day7_retention="5%",
                        payer_conversion_rate="1%",
                        arppu="$1.00",
                        qptr="1",
                        five_minute_retention="20%",
                        home_recommendations="10",
                        client_crash_rate="0.10%",
                        project_id="9682356542",
                        source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                        fetched_at="2026-03-18T01:02:03Z",
                    )
                ],
                "9707829514": [
                    ProjectDailyMetricsRecord(
                        report_date="2026-03-18",
                        peak_ccu="200",
                        average_session_time="12m",
                        day1_retention="12%",
                        day7_retention="6%",
                        payer_conversion_rate="2%",
                        arppu="$2.00",
                        qptr="2",
                        five_minute_retention="25%",
                        home_recommendations="20",
                        client_crash_rate="0.20%",
                        project_id="9707829514",
                        source_url="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
                        fetched_at="2026-03-18T01:02:03Z",
                    )
                ],
            },
            failures=(),
        )
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client
        sync_sheet.side_effect = [
            MagicMock(url="https://feishu.cn/sheets/project-one"),
            MagicMock(url="https://feishu.cn/sheets/project-two"),
        ]

        _notify_success(cfg, report_payload)

        self.assertEqual(2, sync_sheet.call_count)
        self.assertEqual(2, feishu_client.send_group_markdown.call_count)
        self.assertEqual(
            ["https://feishu.cn/sheets/project-one", "https://feishu.cn/sheets/project-two"],
            [call.args[0] for call in feishu_client.send_group_markdown.call_args_list],
        )

    @patch("app.main._sync_project_metrics_sheet")
    @patch("app.main.FeishuClient")
    def test_project_metrics_partial_success_sends_sheet_urls_and_failure_summary(
        self,
        feishu_client_cls,
        sync_sheet,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
        )
        report_payload = ProjectMetricsReportPayload(
            records_by_project_id={
                "9682356542": [
                    ProjectDailyMetricsRecord(
                        report_date="2026-03-18",
                        peak_ccu="100",
                        average_session_time="10m",
                        day1_retention="10%",
                        day7_retention="5%",
                        payer_conversion_rate="1%",
                        arppu="$1.00",
                        qptr="1",
                        five_minute_retention="20%",
                        home_recommendations="10",
                        client_crash_rate="0.10%",
                        project_id="9682356542",
                        source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                        fetched_at="2026-03-18T01:02:03Z",
                    )
                ]
            },
            failures=(
                ProjectMetricsFetchFailure(
                    project_id="9707829514",
                    overview_url="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
                    reason="Creator 后台请求被重定向到登录页，请检查 Cookie 是否有效",
                ),
            ),
        )
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client
        sync_sheet.return_value = MagicMock(url="https://feishu.cn/sheets/project-one")

        _notify_success(cfg, report_payload)

        self.assertEqual(1, sync_sheet.call_count)
        self.assertEqual(2, feishu_client.send_group_markdown.call_count)
        self.assertEqual(
            "https://feishu.cn/sheets/project-one",
            feishu_client.send_group_markdown.call_args_list[0].args[0],
        )
        self.assertIn(
            "项目 9707829514",
            feishu_client.send_group_markdown.call_args_list[1].args[0],
        )

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_fetch_report_payload_keeps_successful_projects_when_one_project_fails(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
        )
        client = MagicMock()
        client_cls.return_value = client
        first_project_records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-18",
                peak_ccu="100",
                average_session_time="10m",
                day1_retention="10%",
                day7_retention="5%",
                payer_conversion_rate="1%",
                arppu="$1.00",
                qptr="1",
                five_minute_retention="20%",
                home_recommendations="10",
                client_crash_rate="0.10%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-18T01:02:03Z",
            )
        ]

        def fetch_project_daily_metrics(overview_url: str, *, report_dates=None):
            self.assertIsNotNone(report_dates)
            if "9682356542" in overview_url:
                return first_project_records
            raise RobloxCreatorMetricsClientError("Creator 后台请求被重定向到登录页，请检查 Cookie 是否有效")

        client.fetch_project_daily_metrics.side_effect = fetch_project_daily_metrics

        report_payload = _fetch_report_payload(cfg)

        self.assertEqual(first_project_records, report_payload.records_by_project_id["9682356542"])
        self.assertEqual(1, len(report_payload.failures))
        self.assertEqual("9707829514", report_payload.failures[0].project_id)
        self.assertIn("Cookie", report_payload.failures[0].reason)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_fetch_report_payload_keeps_failure_payload_when_all_project_metrics_fetches_fail(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_daily_metrics.side_effect = [
            RobloxCreatorMetricsClientError("项目 9682356542 缺少 peak_ccu"),
            RobloxCreatorMetricsClientError("项目 9707829514 缺少 peak_ccu"),
        ]

        report_payload = _fetch_report_payload(cfg)

        self.assertEqual({}, report_payload.records_by_project_id)
        self.assertEqual(["9682356542", "9707829514"], [failure.project_id for failure in report_payload.failures])
        self.assertIn("peak_ccu", report_payload.failures[0].reason)

    @patch("app.main._sync_project_metrics_sheet")
    @patch("app.main.FeishuClient")
    def test_project_metrics_all_failures_sends_failure_summary_without_sheet_sync(
        self,
        feishu_client_cls,
        sync_sheet,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
        )
        report_payload = ProjectMetricsReportPayload(
            records_by_project_id={},
            failures=(
                ProjectMetricsFetchFailure(
                    project_id="9682356542",
                    overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                    reason="Creator 后台请求失败",
                ),
            ),
        )
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client

        _notify_success(cfg, report_payload)

        sync_sheet.assert_not_called()
        feishu_client.send_group_markdown.assert_called_once()
        message = feishu_client.send_group_markdown.call_args.args[0]
        self.assertIn("项目日报抓取异常", message)
        self.assertIn("项目 9682356542", message)


if __name__ == "__main__":
    unittest.main()
