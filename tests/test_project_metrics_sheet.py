from __future__ import annotations

import unittest

from app.project_metrics_models import ProjectDailyMetricsRecord
from app.project_metrics_sheet import (
    PROJECT_METRICS_HEADERS,
    build_project_metrics_table,
    build_project_metrics_values,
)


class ProjectMetricsSheetTests(unittest.TestCase):
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

    def test_build_project_metrics_table_adds_rows_in_date_desc_order(self) -> None:
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-10",
                average_ccu="100",
                peak_ccu="200",
                average_session_time="10m",
                day1_retention="30%",
                day7_retention="10%",
                payer_conversion_rate="2%",
                arppu="$5.00",
                qptr="3%",
                five_minute_retention="35%",
                home_recommendations="50",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                average_ccu="120",
                peak_ccu="220",
                average_session_time="12m",
                day1_retention="32%",
                day7_retention="12%",
                payer_conversion_rate="2.2%",
                arppu="$6.00",
                qptr="4%",
                five_minute_retention="37%",
                home_recommendations="60",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table([], records)

        self.assertEqual(PROJECT_METRICS_HEADERS, table_state.rows[0])
        self.assertEqual(["2026-03-12", "2026-03-10"], [row[0] for row in table_state.rows[1:]])

    def test_build_project_metrics_table_merges_existing_rows_without_clearing_history(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11", "100", "200", "", "", "", "", "", "", "", "", "2026-03-11T01:02:03Z"],
            ["2026-03-10", "90", "180", "", "", "", "", "", "", "", "", "2026-03-10T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                average_ccu="120",
                peak_ccu="220",
                average_session_time="12m",
                day1_retention="32%",
                day7_retention="12%",
                payer_conversion_rate="2.2%",
                arppu="$6.00",
                qptr="4%",
                five_minute_retention="37%",
                home_recommendations="60",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                average_ccu="130",
                peak_ccu="230",
                average_session_time="13m",
                day1_retention="33%",
                day7_retention="13%",
                payer_conversion_rate="2.3%",
                arppu="$6.50",
                qptr="4.5%",
                five_minute_retention="38%",
                home_recommendations="61",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table(existing_rows, records)

        self.assertEqual(["2026-03-12", "2026-03-11", "2026-03-10"], [row[0] for row in table_state.rows[1:]])
        self.assertEqual("130", table_state.rows[2][1])
        self.assertEqual("13m", table_state.rows[2][3])
        self.assertEqual("90", table_state.rows[3][1])

    def test_build_project_metrics_table_keeps_existing_value_when_new_value_missing(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11", "100", "200", "15m", "", "", "", "", "", "", "", "2026-03-11T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                average_ccu="130",
                peak_ccu="230",
                average_session_time="",
                day1_retention="33%",
                day7_retention="",
                payer_conversion_rate="",
                arppu="",
                qptr="",
                five_minute_retention="",
                home_recommendations="",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table(existing_rows, records)

        self.assertEqual("130", table_state.rows[1][1])
        self.assertEqual("15m", table_state.rows[1][3])


if __name__ == "__main__":
    unittest.main()
