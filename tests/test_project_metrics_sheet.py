from __future__ import annotations

import unittest

from app.config import Config
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.project_metrics_sheet import (
    PROJECT_METRICS_HEADERS,
    build_project_metrics_rebuild_rows,
    build_project_metrics_table,
    build_project_metrics_values,
    resolve_project_metrics_variables,
)


class ProjectMetricsSheetTests(unittest.TestCase):
    def test_resolve_project_metrics_variables_returns_each_configured_project(self) -> None:
        variables = resolve_project_metrics_variables(
            Config(
                roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                roblox_creator_overview_url_2="https://create.roblox.com/dashboard/creations/experiences/9707829514/overview",
                feishu_project_metrics_spreadsheet_title="Shoot Or Shot",
                feishu_project_metrics_2_spreadsheet_title="项目 9707829514",
            )
        )

        self.assertEqual(["9682356542", "9707829514"], [item.project_id for item in variables])
        self.assertEqual(
            ["Shoot Or Shot", "项目 9707829514"],
            [item.spreadsheet_title for item in variables],
        )

    def test_build_project_metrics_values_follows_expected_column_order(self) -> None:
        record = ProjectDailyMetricsRecord(
            report_date="2026-03-12",
            peak_ccu="2,345",
            average_session_time="18m 30s",
            average_session_time_rank="82th",
            day1_retention="31%",
            day1_retention_rank="71th",
            day7_retention="12%",
            day7_retention_rank="63th",
            payer_conversion_rate="2.5%",
            payer_conversion_rate_rank="58th",
            arppu="$8.90",
            arppu_rank="76th",
            qptr="4.2",
            five_minute_retention="40%",
            home_recommendations="98",
            client_crash_rate="0.12%",
            project_id="9682356542",
            source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            fetched_at="2026-03-12T01:02:03Z",
        )

        row = build_project_metrics_values(record)

        self.assertEqual("2026-03-12（周四）", row[0])
        self.assertEqual("2,345", row[1])
        self.assertEqual("18m 30s", row[2])
        self.assertEqual("82th", row[3])
        self.assertEqual("71th", row[5])
        self.assertEqual("63th", row[7])
        self.assertEqual("58th", row[9])
        self.assertEqual("$8.90", row[10])
        self.assertEqual("76th", row[11])
        self.assertEqual("0.12%", row[15])
        self.assertEqual("2026-03-12T01:02:03Z", row[16])

    def test_build_project_metrics_table_adds_rows_in_date_desc_order(self) -> None:
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-10",
                peak_ccu="200",
                average_session_time="10m",
                day1_retention="30%",
                day7_retention="10%",
                payer_conversion_rate="2%",
                arppu="$5.00",
                qptr="3%",
                five_minute_retention="35%",
                home_recommendations="50",
                client_crash_rate="0.10%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                peak_ccu="220",
                average_session_time="12m",
                day1_retention="32%",
                day7_retention="12%",
                payer_conversion_rate="2.2%",
                arppu="$6.00",
                qptr="4%",
                five_minute_retention="37%",
                home_recommendations="60",
                client_crash_rate="0.11%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table([], records)

        self.assertEqual(PROJECT_METRICS_HEADERS, table_state.rows[0])
        self.assertEqual(["2026-03-12（周四）", "2026-03-10（周二）"], [row[0] for row in table_state.rows[1:]])

    def test_build_project_metrics_table_merges_existing_rows_without_clearing_history(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11", "200", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "2026-03-11T01:02:03Z"],
            ["2026-03-10", "180", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "2026-03-10T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                peak_ccu="220",
                average_session_time="12m",
                day1_retention="32%",
                day7_retention="12%",
                payer_conversion_rate="2.2%",
                arppu="$6.00",
                qptr="4%",
                five_minute_retention="37%",
                home_recommendations="60",
                client_crash_rate="0.11%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                peak_ccu="230",
                average_session_time="13m",
                day1_retention="33%",
                day7_retention="13%",
                payer_conversion_rate="2.3%",
                arppu="$6.50",
                qptr="4.5%",
                five_minute_retention="38%",
                home_recommendations="61",
                client_crash_rate="0.09%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table(existing_rows, records)

        self.assertEqual(
            ["2026-03-12（周四）", "2026-03-11（周三）", "2026-03-10"],
            [row[0] for row in table_state.rows[1:]],
        )
        self.assertEqual("230", table_state.rows[2][1])
        self.assertEqual("13m", table_state.rows[2][2])
        self.assertEqual("180", table_state.rows[3][1])

    def test_build_project_metrics_table_clears_existing_value_when_new_value_missing(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11", "200", "15m", "", "31%", "", "", "", "", "", "", "", "", "", "", "", "2026-03-11T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                peak_ccu="230",
                average_session_time="",
                day1_retention="",
                day7_retention="",
                payer_conversion_rate="",
                arppu="",
                qptr="",
                five_minute_retention="",
                home_recommendations="",
                client_crash_rate="",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table(existing_rows, records)

        self.assertEqual("2026-03-11（周三）", table_state.rows[1][0])
        self.assertEqual("230", table_state.rows[1][1])
        self.assertEqual("15m", table_state.rows[1][2])
        self.assertEqual("31%", table_state.rows[1][4])
        self.assertEqual("2026-03-12T01:02:03Z", table_state.rows[1][16])

    def test_build_project_metrics_rebuild_rows_pads_blank_rows_to_fixed_height(self) -> None:
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                peak_ccu="220",
                average_session_time="12m",
                day1_retention="32%",
                day7_retention="12%",
                payer_conversion_rate="2.2%",
                arppu="$6.00",
                qptr="4%",
                five_minute_retention="37%",
                home_recommendations="60",
                client_crash_rate="0.11%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        rows = build_project_metrics_rebuild_rows([], records, total_rows=5)

        self.assertEqual(5, len(rows))
        self.assertEqual(PROJECT_METRICS_HEADERS, rows[0])
        self.assertEqual("2026-03-12（周四）", rows[1][0])
        self.assertEqual([""] * len(PROJECT_METRICS_HEADERS), rows[-1])

    def test_build_project_metrics_rebuild_rows_preserves_existing_non_empty_cells(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11（周三）", "200", "15m", "82th", "31%", "71th", "", "", "", "", "", "", "4.5%", "", "88", "0.10%", "2026-03-11T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                peak_ccu="",
                average_session_time="",
                day1_retention="",
                day7_retention="",
                payer_conversion_rate="",
                arppu="",
                qptr="",
                five_minute_retention="",
                home_recommendations="",
                client_crash_rate="",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        rows = build_project_metrics_rebuild_rows(existing_rows, records, total_rows=3)

        self.assertEqual("2026-03-11（周三）", rows[1][0])
        self.assertEqual("200", rows[1][1])
        self.assertEqual("15m", rows[1][2])
        self.assertEqual("82th", rows[1][3])
        self.assertEqual("31%", rows[1][4])
        self.assertEqual("71th", rows[1][5])
        self.assertEqual("4.5%", rows[1][12])
        self.assertEqual("88", rows[1][14])
        self.assertEqual("0.10%", rows[1][15])
        self.assertEqual("2026-03-12T01:02:03Z", rows[1][16])

    def test_build_project_metrics_table_updates_existing_rows_with_weekday_suffix(self) -> None:
        existing_rows = [
            PROJECT_METRICS_HEADERS.copy(),
            ["2026-03-11（周三）", "200", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "2026-03-11T01:02:03Z"],
        ]
        records = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                peak_ccu="230",
                average_session_time="13m",
                day1_retention="33%",
                day7_retention="13%",
                payer_conversion_rate="2.3%",
                arppu="$6.50",
                qptr="4.5%",
                five_minute_retention="38%",
                home_recommendations="61",
                client_crash_rate="0.09%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        table_state = build_project_metrics_table(existing_rows, records)

        self.assertEqual("2026-03-11（周三）", table_state.rows[1][0])
        self.assertEqual("230", table_state.rows[1][1])
        self.assertEqual("13m", table_state.rows[1][2])


if __name__ == "__main__":
    unittest.main()
