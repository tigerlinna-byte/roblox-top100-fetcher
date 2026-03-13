from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.config import Config, load_config
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.project_metrics_sheet import (
    PROJECT_METRICS_HEADERS,
    build_project_metrics_table,
    build_project_metrics_values,
)


class ProjectMetricsSheetTests(unittest.TestCase):
    def test_load_config_reads_project_metrics_reset_switch(self) -> None:
        with patch.dict(
            os.environ,
            {
                "FEISHU_PROJECT_METRICS_RESET_BEFORE_SYNC": "true",
            },
            clear=False,
        ):
            cfg = load_config()

        self.assertTrue(cfg.feishu_project_metrics_reset_before_sync)

    def test_build_project_metrics_values_follows_expected_column_order(self) -> None:
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-12",
            average_ccu="1,234",
            peak_ccu="2,345",
            average_session_time="18m 30s",
            day1_retention="31%",
            day7_retention="12%",
            payer_conversion_rate="2.5%",
            arppu="$8.90",
            qptr="4.2",
            five_minute_retention="40%",
            home_recommendations="98",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-12T01:02:03Z",
        )

        row = build_project_metrics_values(record)

        self.assertEqual("2026-03-12", row[0])
        self.assertEqual("1,234", row[1])
        self.assertEqual("2,345", row[2])
        self.assertEqual("18m 30s", row[3])
        self.assertEqual("2026-03-12T01:02:03Z", row[11])

    def test_build_project_metrics_table_adds_first_data_row(self) -> None:
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-12",
            average_ccu="1,234",
            peak_ccu="2,345",
            average_session_time="18m 30s",
            day1_retention="31%",
            day7_retention="12%",
            payer_conversion_rate="2.5%",
            arppu="$8.90",
            qptr="4.2",
            five_minute_retention="40%",
            home_recommendations="98",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-12T01:02:03Z",
        )

        table_state = build_project_metrics_table([], record)

        self.assertEqual(PROJECT_METRICS_HEADERS, table_state.rows[0])
        self.assertEqual("2026-03-12", table_state.rows[1][0])
        self.assertEqual(2, table_state.updated_row_index)
        self.assertTrue(table_state.was_updated)

    def test_build_project_metrics_table_updates_existing_date(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            [
                "2026-03-11",
                "900",
                "1,500",
                "15m",
                "30%",
                "10%",
                "2.1%",
                "$6.20",
                "3.1",
                "35%",
                "70",
                "2026-03-11T01:02:03Z",
            ],
            [
                "2026-03-12",
                "1,000",
                "1,800",
                "16m",
                "31%",
                "11%",
                "2.2%",
                "$6.50",
                "3.2",
                "36%",
                "71",
                "2026-03-12T01:02:03Z",
            ],
        ]
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-12",
            average_ccu="1,234",
            peak_ccu="2,345",
            average_session_time="18m 30s",
            day1_retention="31%",
            day7_retention="12%",
            payer_conversion_rate="2.5%",
            arppu="$8.90",
            qptr="4.2",
            five_minute_retention="40%",
            home_recommendations="98",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-12T09:09:09Z",
        )

        table_state = build_project_metrics_table(existing_rows, record)

        self.assertEqual(3, len(table_state.rows))
        self.assertEqual("1,234", table_state.rows[2][1])
        self.assertEqual("2026-03-12T09:09:09Z", table_state.rows[2][11])
        self.assertEqual(3, table_state.updated_row_index)
        self.assertTrue(table_state.was_updated)

    def test_build_project_metrics_table_inserts_newer_date_at_top(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            [
                "2026-03-12",
                "1,000",
                "1,800",
                "16m",
                "31%",
                "11%",
                "2.2%",
                "$6.50",
                "3.2",
                "36%",
                "71",
                "2026-03-12T01:02:03Z",
            ],
            [
                "2026-03-11",
                "900",
                "1,500",
                "15m",
                "30%",
                "10%",
                "2.1%",
                "$6.20",
                "3.1",
                "35%",
                "70",
                "2026-03-11T01:02:03Z",
            ],
        ]
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-13",
            average_ccu="1,500",
            peak_ccu="2,600",
            average_session_time="20m",
            day1_retention="32%",
            day7_retention="13%",
            payer_conversion_rate="2.8%",
            arppu="$9.10",
            qptr="4.8",
            five_minute_retention="41%",
            home_recommendations="101",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-13T09:09:09Z",
        )

        table_state = build_project_metrics_table(existing_rows, record)

        self.assertTrue(table_state.was_updated)
        self.assertEqual(2, table_state.updated_row_index)
        self.assertEqual("2026-03-13", table_state.rows[1][0])
        self.assertEqual("2026-03-12", table_state.rows[2][0])
        self.assertEqual("2026-03-11", table_state.rows[3][0])

    def test_build_project_metrics_table_skips_older_than_last_row(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            [
                "2026-03-12",
                "1,000",
                "1,800",
                "16m",
                "31%",
                "11%",
                "2.2%",
                "$6.50",
                "3.2",
                "36%",
                "71",
                "2026-03-12T01:02:03Z",
            ],
            [
                "2026-03-11",
                "900",
                "1,500",
                "15m",
                "30%",
                "10%",
                "2.1%",
                "$6.20",
                "3.1",
                "35%",
                "70",
                "2026-03-11T01:02:03Z",
            ],
        ]
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-10",
            average_ccu="800",
            peak_ccu="1,200",
            average_session_time="14m",
            day1_retention="29%",
            day7_retention="9%",
            payer_conversion_rate="1.9%",
            arppu="$5.80",
            qptr="2.9",
            five_minute_retention="34%",
            home_recommendations="50",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-10T09:09:09Z",
        )

        table_state = build_project_metrics_table(existing_rows, record)

        self.assertFalse(table_state.was_updated)
        self.assertEqual(0, table_state.updated_row_index)
        self.assertEqual(existing_rows, table_state.rows)

    def test_build_project_metrics_table_skips_missing_middle_date(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            [
                "2026-03-13",
                "1,500",
                "2,600",
                "20m",
                "32%",
                "13%",
                "2.8%",
                "$9.10",
                "4.8",
                "41%",
                "101",
                "2026-03-13T09:09:09Z",
            ],
            [
                "2026-03-11",
                "900",
                "1,500",
                "15m",
                "30%",
                "10%",
                "2.1%",
                "$6.20",
                "3.1",
                "35%",
                "70",
                "2026-03-11T01:02:03Z",
            ],
        ]
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-12",
            average_ccu="1,100",
            peak_ccu="1,900",
            average_session_time="17m",
            day1_retention="31%",
            day7_retention="11%",
            payer_conversion_rate="2.3%",
            arppu="$6.90",
            qptr="3.4",
            five_minute_retention="37%",
            home_recommendations="75",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-12T09:09:09Z",
        )

        table_state = build_project_metrics_table(existing_rows, record)

        self.assertFalse(table_state.was_updated)
        self.assertEqual(0, table_state.updated_row_index)
        self.assertEqual(existing_rows, table_state.rows)


if __name__ == "__main__":
    unittest.main()
