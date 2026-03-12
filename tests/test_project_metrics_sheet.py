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


if __name__ == "__main__":
    unittest.main()
