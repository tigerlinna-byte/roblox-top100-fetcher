from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import Config, load_config
from app.main import ProjectMetricsReportPayload, _fetch_report_payload, _resolve_roblox_money_variables, _write_report_outputs
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.project_metrics_sheet import (
    get_saved_project_metrics_target,
    resolve_project_metrics_variables,
    save_project_metrics_target,
)


TNT_OVERVIEW_URL = "https://create.roblox.com/dashboard/creations/experiences/10767359040/overview"


class TntProjectTests(unittest.TestCase):
    @patch("app.main.RobloxCreatorMetricsClient")
    def test_tnt_does_not_fetch_before_its_first_complete_business_day(self, client_cls) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url_6=TNT_OVERVIEW_URL,
            feishu_timezone="UTC",
        )
        for day in (25, 26):
            with self.subTest(day=day), patch(
                "app.roblox_creator_metrics_client._business_midnight_now",
                return_value=datetime(2026, 9, day, tzinfo=timezone.utc),
            ):
                payload = _fetch_report_payload(cfg)
                client_cls.return_value.fetch_project_daily_metrics.assert_not_called()
                self.assertEqual({"10767359040": []}, payload.records_by_project_id)
                self.assertEqual((), payload.failures)

    @patch("app.main.RobloxCreatorMetricsClient")
    def test_tnt_fetch_window_starts_on_september_26_and_ends_yesterday(self, client_cls) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url_6=TNT_OVERVIEW_URL,
            feishu_timezone="UTC",
        )
        fetch_metrics = client_cls.return_value.fetch_project_daily_metrics
        record = ProjectDailyMetricsRecord(report_date="2026-09-26", project_id="10767359040", peak_ccu="100")
        fetch_metrics.return_value = [record]
        for current_day, expected_dates in (
            (27, (date(2026, 9, 26),)),
            (29, (date(2026, 9, 26), date(2026, 9, 27), date(2026, 9, 28))),
        ):
            with self.subTest(current_day=current_day), patch(
                "app.roblox_creator_metrics_client._business_midnight_now",
                return_value=datetime(2026, 9, current_day, tzinfo=timezone.utc),
            ):
                fetch_metrics.reset_mock()
                payload = _fetch_report_payload(cfg)
                fetch_metrics.assert_called_once()
                self.assertEqual((TNT_OVERVIEW_URL,), fetch_metrics.call_args.args)
                self.assertEqual(expected_dates, tuple(fetch_metrics.call_args.kwargs["report_dates"]))
                self.assertEqual({"10767359040": [record]}, payload.records_by_project_id)
                self.assertEqual((), payload.failures)

    def test_sixth_slot_loads_and_persists_its_own_sheet_identifiers(self) -> None:
        with patch.dict(os.environ, {
            "ROBLOX_CREATOR_OVERVIEW_URL_6": TNT_OVERVIEW_URL,
            "FEISHU_PROJECT_METRICS_6_SPREADSHEET_TOKEN": "sht_tnt",
            "FEISHU_PROJECT_METRICS_6_SHEET_ID": "sheet_tnt",
        }, clear=True):
            cfg = load_config()

        variables, = resolve_project_metrics_variables(cfg)
        self.assertEqual("10767359040", variables.project_id)
        self.assertEqual(TNT_OVERVIEW_URL, variables.overview_url)
        self.assertEqual("TNT", variables.spreadsheet_title)
        target = get_saved_project_metrics_target(cfg, variables)
        self.assertIsNotNone(target)
        self.assertEqual("https://feishu.cn/sheets/sht_tnt", target.url)
        self.assertEqual("sheet_tnt", target.sheet_id)
        github_client = MagicMock()
        save_project_metrics_target(github_client, target, variables)
        self.assertEqual(
            [("FEISHU_PROJECT_METRICS_6_SPREADSHEET_TOKEN", "sht_tnt"), ("FEISHU_PROJECT_METRICS_6_SHEET_ID", "sheet_tnt")],
            [call.args for call in github_client.upsert_repository_variable.call_args_list],
        )

    def test_sixth_slot_is_not_included_in_revenue_reports(self) -> None:
        cfg = Config(
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_6=TNT_OVERVIEW_URL,
        )
        self.assertEqual(["9682356542", "10767359040"], [item.project_id for item in resolve_project_metrics_variables(cfg)])
        self.assertEqual(["9682356542"], [item.project_id for item in _resolve_roblox_money_variables(cfg)])

    @patch("app.main.write_project_metrics_output")
    def test_tnt_records_are_included_in_daily_artifacts(self, write_output) -> None:
        cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            roblox_creator_overview_url_6=TNT_OVERVIEW_URL,
        )
        record = ProjectDailyMetricsRecord(report_date="2026-09-26", project_id="10767359040", peak_ccu="100")
        payload = ProjectMetricsReportPayload(records_by_project_id={"10767359040": [record]}, failures=())
        _write_report_outputs(cfg, payload)
        write_output.assert_called_once_with(cfg.output_dir, [record], prefix="project_metrics")


if __name__ == "__main__":
    unittest.main()
