from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.main import (
    ProjectMetricsFetchFailure,
    ProjectMetricsReportPayload,
    _fetch_report_payload,
    _notify_success,
    _persist_top_trending_previous_ranks,
    _resolve_project_metrics_report_variables,
    _write_report_outputs,
)
from app.models import GameRecord
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.roblox_money_models import (
    RobloxMoneyFetchFailure,
    RobloxMoneyProjectRevenue,
    RobloxMoneyReportPayload,
)
from app.roblox_client import RobloxClientError
from app.roblox_creator_metrics_client import RobloxCreatorMetricsClientError


class MainTests(unittest.TestCase):
    @patch("app.main._persist_top_trending_previous_ranks")
    @patch("app.main.FeishuClient")
    def test_top_trending_success_sends_briefing_without_sheet_url(self, feishu_client_cls, persist_ranks) -> None:
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
            "top_earning": [],
        }
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client

        _notify_success(cfg, report_payload)

        feishu_client.send_group_card.assert_called_once()
        feishu_client.send_group_markdown.assert_not_called()
        persist_ranks.assert_called_once_with(cfg, report_payload)
        briefing_card = feishu_client.send_group_card.call_args.args[0]
        self.assertEqual("今日关注（2026-03-14）", briefing_card["header"]["title"]["content"])

    @patch("app.main.FeishuClient")
    def test_top100_success_does_not_send_feishu_message(self, feishu_client_cls) -> None:
        cfg = Config(run_report_mode="top100_message")

        _notify_success(cfg, [GameRecord(rank=1, place_id=101, name="Game A")])

        feishu_client_cls.assert_not_called()

    @patch("app.main.RobloxClient")
    def test_fetch_top_trending_payload_includes_top_earning_300(self, client_cls) -> None:
        cfg = Config(run_report_mode="top_trending_sheet")
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_games_by_sort_id.side_effect = [
            [GameRecord(rank=1, place_id=101, name="Trending")],
            [GameRecord(rank=1, place_id=201, name="Coming")],
            [GameRecord(rank=1, place_id=301, name="Playing")],
        ]
        client.fetch_top_earning_games.return_value = [
            GameRecord(rank=1, place_id=401, name="Earning"),
        ]

        report_payload = _fetch_report_payload(cfg)

        self.assertEqual(["top_trending_v4", "up_and_coming_v4", "top_playing_now", "top_earning"], list(report_payload))
        self.assertEqual(
            [
                (("Top_Trending_V4",), {"include_thumbnails": False}),
                (("Up_And_Coming_V4",), {"include_thumbnails": False}),
                (("top-playing-now",), {"include_thumbnails": False}),
            ],
            [(call.args, call.kwargs) for call in client.fetch_games_by_sort_id.call_args_list],
        )
        client.fetch_top_earning_games.assert_called_once_with(limit=300, include_thumbnails=False)

    @patch("app.main.RobloxClient")
    def test_fetch_top_trending_payload_omits_failed_top_earning(self, client_cls) -> None:
        cfg = Config(run_report_mode="top_trending_sheet")
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_games_by_sort_id.side_effect = [
            [GameRecord(rank=1, place_id=101, name="Trending")],
            [GameRecord(rank=1, place_id=201, name="Coming")],
            [GameRecord(rank=1, place_id=301, name="Playing")],
        ]
        client.fetch_top_earning_games.side_effect = RobloxClientError("Request failed")

        report_payload = _fetch_report_payload(cfg)

        self.assertEqual(["top_trending_v4", "up_and_coming_v4", "top_playing_now"], list(report_payload))
        client.fetch_top_earning_games.assert_called_once_with(limit=300, include_thumbnails=False)

    @patch("app.main.GitHubClient")
    def test_persist_top_trending_previous_ranks_without_sheet_target(self, github_client_cls) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            feishu_top_trending_test_prev_ranks='{"history":[{"place_ids":[99],"ranks":{"99":1}}]}',
        )
        github_client = github_client_cls.return_value

        _persist_top_trending_previous_ranks(
            cfg,
            {
                "top_trending_v4": [GameRecord(rank=1, place_id=101, name="Game A")],
                "up_and_coming_v4": [],
                "top_playing_now": [],
                "top_earning": [],
            },
        )

        variable_names = [call.args[0] for call in github_client.upsert_repository_variable.call_args_list]
        self.assertIn("FEISHU_TOP_TRENDING_TEST_PREV_RANKS", variable_names)
        self.assertIn("FEISHU_UP_AND_COMING_TEST_PREV_RANKS", variable_names)
        saved_payload = github_client.upsert_repository_variable.call_args_list[0].args[1]
        self.assertIn('"101":1', saved_payload)

    @patch("app.main.GitHubClient")
    def test_sync_top_trending_sheet_skips_missing_sheet_payload(self, github_client_cls) -> None:
        from app.main import _sync_top_trending_sheet
        from app.top_trending_sheet import SheetTarget, SpreadsheetTarget

        cfg = Config(run_report_mode="top_trending_sheet")
        feishu_client = MagicMock()
        target = SpreadsheetTarget(
            spreadsheet_token="shtcn_test",
            sheets=(
                SheetTarget(
                    sort_id="Top_Trending_V4",
                    title="top_trending_v4",
                    variable_name="FEISHU_TOP_TRENDING_SHEET_ID",
                    previous_ranks_variable_name="FEISHU_TOP_TRENDING_PREV_RANKS",
                    sheet_id="sheet_1",
                ),
                SheetTarget(
                    sort_id="top-earning",
                    title="top_earning",
                    variable_name="FEISHU_TOP_EARNING_SHEET_ID",
                    previous_ranks_variable_name="FEISHU_TOP_EARNING_PREV_RANKS",
                    sheet_id="sheet_2",
                ),
            ),
            url="https://feishu.cn/sheets/shtcn_test",
        )
        with patch("app.main.get_saved_spreadsheet_target", return_value=target):
            _sync_top_trending_sheet(
                cfg,
                {"top_trending_v4": [GameRecord(rank=1, place_id=101, name="Game A")]},
                feishu_client,
            )

        feishu_client.write_sheet_values.assert_called_once()
        github_client = github_client_cls.return_value
        github_client.upsert_repository_variable.assert_called_once()

    @patch("app.main._sync_project_metrics_sheet")
    @patch("app.main.FeishuClient")
    def test_project_metrics_success_sends_each_project_sheet_url(self, feishu_client_cls, sync_sheet) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
            roblox_creator_overview_url_3="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
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
                "10170801715": [
                    ProjectDailyMetricsRecord(
                        report_date="2026-05-31",
                        peak_ccu="300",
                        average_session_time="14m",
                        day1_retention="14%",
                        day7_retention="7%",
                        payer_conversion_rate="3%",
                        arppu="$3.00",
                        qptr="3",
                        five_minute_retention="30%",
                        home_recommendations="30",
                        client_crash_rate="0.30%",
                        project_id="10170801715",
                        source_url="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
                        fetched_at="2026-05-31T01:02:03Z",
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
            MagicMock(url="https://feishu.cn/sheets/project-three"),
        ]

        _notify_success(cfg, report_payload)

        self.assertEqual(3, sync_sheet.call_count)
        self.assertEqual(3, feishu_client.send_group_markdown.call_count)
        self.assertEqual(
            [
                "https://feishu.cn/sheets/project-one",
                "https://feishu.cn/sheets/project-two",
                "https://feishu.cn/sheets/project-three",
            ],
            [call.args[0] for call in feishu_client.send_group_markdown.call_args_list],
        )

    def test_project_metrics_report_variables_can_disable_second_project(self) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
            roblox_creator_overview_url_3="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
            roblox_project_metrics_disable_second_project=True,
        )

        variables = _resolve_project_metrics_report_variables(cfg)

        self.assertEqual(["9682356542", "10170801715"], [item.project_id for item in variables])

    @patch("app.main.write_project_metrics_output")
    def test_project_metrics_output_ignores_disabled_second_project(self, write_project_metrics_output) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            output_dir="./data",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
            roblox_creator_overview_url_3="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
            roblox_project_metrics_disable_second_project=True,
        )
        first_record = ProjectDailyMetricsRecord(
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
        second_record = ProjectDailyMetricsRecord(
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
        third_record = ProjectDailyMetricsRecord(
            report_date="2026-05-31",
            peak_ccu="300",
            average_session_time="14m",
            day1_retention="14%",
            day7_retention="7%",
            payer_conversion_rate="3%",
            arppu="$3.00",
            qptr="3",
            five_minute_retention="30%",
            home_recommendations="30",
            client_crash_rate="0.30%",
            project_id="10170801715",
            source_url="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
            fetched_at="2026-05-31T01:02:03Z",
        )
        write_project_metrics_output.return_value = ("data/project_metrics_2026-03-18.json", "data/project_metrics_2026-03-18.csv")

        _write_report_outputs(
            cfg,
            ProjectMetricsReportPayload(
                records_by_project_id={
                    "9682356542": [first_record],
                    "9707829514": [second_record],
                    "10170801715": [third_record],
                },
                failures=(),
            ),
        )

        write_project_metrics_output.assert_called_once_with("./data", [first_record, third_record], prefix="project_metrics")

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

        def fetch_project_daily_metrics(overview_url: str, *, report_dates=None, requested_fields_by_date=None):
            self.assertIsNotNone(report_dates)
            self.assertIsNotNone(requested_fields_by_date)
            self.assertEqual(tuple(report_dates), tuple(requested_fields_by_date))
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

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_uses_single_report_date_and_month_to_date(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
            feishu_project_metrics_spreadsheet_title="Shoot Or Shot",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={
                "2026-05-01": 1000,
                "2026-05-02": 2000,
                "2026-05-03": 3000,
                "2026-05-04": 4000,
            },
        )

        payload = _fetch_report_payload(cfg)

        revenue = payload.project_revenues[0]
        self.assertEqual("2026-05-04", revenue.report_date)
        self.assertEqual("2026-05-01", revenue.month_start_date)
        self.assertEqual(4000, revenue.daily_robux)
        self.assertEqual(10000, revenue.month_to_date_robux)
        self.assertEqual(14.0, revenue.daily_usd)
        self.assertEqual(35.0, revenue.month_to_date_usd)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_uses_troll_project_when_project_metrics_disable_is_enabled(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
            roblox_creator_overview_url_3="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
            roblox_project_metrics_disable_second_project=True,
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={"2026-05-04": 4000},
        )

        payload = _fetch_report_payload(cfg)

        self.assertEqual(["9682356542", "10170801715"], [item.project_id for item in payload.project_revenues])
        self.assertEqual(2, client.fetch_project_revenue_series.call_count)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_skips_second_project_without_troll_project(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={"2026-05-04": 4000},
        )

        payload = _fetch_report_payload(cfg)

        self.assertEqual(["9682356542"], [item.project_id for item in payload.project_revenues])
        self.assertEqual(1, client.fetch_project_revenue_series.call_count)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_uses_natural_month_after_may(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={
                "2026-05-31": 9000,
                "2026-06-01": 1000,
                "2026-06-02": 2000,
            },
        )

        payload = _fetch_report_payload(cfg)

        revenue = payload.project_revenues[0]
        self.assertEqual("2026-06-02", revenue.report_date)
        self.assertEqual("2026-06-01", revenue.month_start_date)
        self.assertEqual(2000, revenue.daily_robux)
        self.assertEqual(3000, revenue.month_to_date_robux)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_uses_latest_available_revenue_date(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={
                "2026-05-01": 1000,
                "2026-05-02": 2000,
                "2026-05-03": 3000,
            },
        )

        payload = _fetch_report_payload(cfg)

        revenue = payload.project_revenues[0]
        self.assertEqual("2026-05-03", revenue.report_date)
        self.assertEqual("2026-05-01", revenue.month_start_date)
        self.assertEqual(3000, revenue.daily_robux)
        self.assertEqual(6000, revenue.month_to_date_robux)
        self.assertEqual((), payload.failures)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_ignores_values_before_start_date(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_start_date="2026-05-01",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.return_value = MagicMock(
            metric="Revenue",
            values={
                "2026-04-30": 9000,
                "2026-05-01": 1000,
            },
        )

        payload = _fetch_report_payload(cfg)

        revenue = payload.project_revenues[0]
        self.assertEqual("2026-05-01", revenue.report_date)
        self.assertEqual("2026-05-01", revenue.month_start_date)
        self.assertEqual(1000, revenue.daily_robux)
        self.assertEqual(1000, revenue.month_to_date_robux)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_roblox_money_payload_keeps_failure_when_project_fetch_fails(
        self,
        client_cls,
    ) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_usd_per_100k_robux="350",
        )
        client = MagicMock()
        client_cls.return_value = client
        client.fetch_project_revenue_series.side_effect = RobloxCreatorMetricsClientError("未找到 Roblox 总收入指标数据")

        payload = _fetch_report_payload(cfg)

        self.assertEqual((), payload.project_revenues)
        self.assertEqual(1, len(payload.failures))
        self.assertIn("总收入", payload.failures[0].reason)

    def test_roblox_money_payload_requires_usd_conversion_rate(self) -> None:
        cfg = Config(
            run_report_mode="roblox_money",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_money_usd_per_100k_robux="",
        )

        with self.assertRaisesRegex(RobloxCreatorMetricsClientError, "ROBLOX_MONEY_USD_PER_100K_ROBUX 未配置"):
            _fetch_report_payload(cfg)

    @patch("app.main.FeishuClient")
    def test_roblox_money_success_sends_card(self, feishu_client_cls) -> None:
        cfg = Config(run_report_mode="roblox_money")
        report_payload = RobloxMoneyReportPayload(
            project_revenues=(
                RobloxMoneyProjectRevenue(
                    project_id="9682356542",
                    project_name="Shoot Or Shot",
                    source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                    revenue_metric="Revenue",
                    report_date="2026-05-04",
                    month_start_date="2026-05-01",
                    month_end_date="2026-05-04",
                    daily_robux=4000,
                    month_to_date_robux=10000,
                    usd_per_100k_robux=350,
                    fetched_at="2026-05-05T01:20:00Z",
                ),
            ),
            failures=(
                RobloxMoneyFetchFailure(
                    project_id="1234567890",
                    project_name="项目 1234567890",
                    overview_url="https://create.roblox.com/dashboard/creations/experiences/1234567890/overview",
                    reason="未找到 Roblox 总收入指标数据",
                ),
            ),
        )
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client

        _notify_success(cfg, report_payload)

        feishu_client.send_group_card.assert_called_once()
        feishu_client.send_group_markdown.assert_not_called()
        card = feishu_client.send_group_card.call_args.args[0]
        self.assertEqual("Roblox 收入日报（2026-05-04）", card["header"]["title"]["content"])
        message = card["elements"][0]["content"]
        self.assertIn("**收入概览**", message)
        self.assertIn("**<font color='blue'>Shoot Or Shot</font>**", message)
        self.assertIn("**<font color='green'>$14.00</font>**（4,000 Robux）", message)
        self.assertIn("**<font color='blue'>$35.00</font>**（10,000 Robux）", message)
        self.assertIn("**抓取异常**", message)
        self.assertIn("**<font color='red'>项目 1234567890</font>**", message)


if __name__ == "__main__":
    unittest.main()
