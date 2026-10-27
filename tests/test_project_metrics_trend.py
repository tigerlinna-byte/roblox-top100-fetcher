from __future__ import annotations

import unittest
from unittest.mock import patch

from app.daily_brief_rules import STANDARD_ALERT_PROFILE
from app.project_metrics_sheet import PROJECT_METRICS_FIELD_TO_HEADER, PROJECT_METRICS_HEADERS
from app.project_metrics_trend import build_project_trend_summary, parse_metric_number


PROJECT_ID = "10170801715"


def _row(report_date: str, **values: str) -> list[str]:
    row = [""] * len(PROJECT_METRICS_HEADERS)
    row[0] = f"{report_date}（周一）"
    for field_name, value in values.items():
        row[PROJECT_METRICS_HEADERS.index(PROJECT_METRICS_FIELD_TO_HEADER[field_name])] = value
    return row


def _rows_with_history(report_values: dict[str, str], history_values: dict[str, str]) -> list[list[str]]:
    rows = [PROJECT_METRICS_HEADERS.copy(), _row("2026-10-26", **report_values)]
    for day in range(19, 26):
        rows.append(_row(f"2026-10-{day:02d}", **history_values))
    return rows


class ProjectMetricsTrendTests(unittest.TestCase):
    def test_parse_metric_number_handles_display_formats(self) -> None:
        self.assertEqual(1234.0, parse_metric_number("1,234"))
        self.assertEqual(12.5, parse_metric_number("12.5%"))
        self.assertEqual(0.12, parse_metric_number("$0.12"))
        self.assertEqual(605.0, parse_metric_number("10m 5s"))
        self.assertEqual(3720.0, parse_metric_number("1h 2m"))
        self.assertEqual(45.0, parse_metric_number("45s"))
        self.assertIsNone(parse_metric_number(""))
        self.assertIsNone(parse_metric_number("-"))

    def test_relaxed_profile_alerts_only_on_double_or_half(self) -> None:
        rows = _rows_with_history(
            {"peak_ccu": "2,100", "day1_retention": "4.9%", "average_session_time": "10m 0s"},
            {"peak_ccu": "1,000", "day1_retention": "10%", "average_session_time": "7m 0s"},
        )

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertEqual("2026-10-26", summary.report_date)
        self.assertEqual(
            [("peak_ccu", "rise"), ("day1_retention", "fall")],
            [(alert.metric, alert.direction) for alert in summary.alerts],
        )
        self.assertEqual("2,100", summary.alerts[0].current_text)
        self.assertAlmostEqual(1.1, summary.alerts[0].change_ratio)

    def test_standard_profile_uses_tighter_thresholds(self) -> None:
        rows = _rows_with_history({"peak_ccu": "1,300"}, {"peak_ccu": "1,000"})

        with patch.dict(
            "app.metric_baseline.PROJECT_ALERT_PROFILE_BY_PROJECT_ID",
            {PROJECT_ID: STANDARD_ALERT_PROFILE},
        ):
            summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertEqual(["peak_ccu"], [alert.metric for alert in summary.alerts])

    def test_crash_rate_only_alerts_on_rise(self) -> None:
        rows = _rows_with_history({"peak_ccu": "1,000", "client_crash_rate": "0.1%"}, {"peak_ccu": "1,000", "client_crash_rate": "1%"})

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertEqual((), summary.alerts)

    def test_insufficient_baseline_skips_alerts_but_keeps_summary(self) -> None:
        rows = [
            PROJECT_METRICS_HEADERS.copy(),
            _row("2026-10-26", peak_ccu="5,000", day1_retention="20%"),
            _row("2026-10-25", peak_ccu="100"),
        ]

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertEqual((), summary.alerts)
        self.assertEqual((("峰值PCU", "5,000"), ("D1", "20%")), summary.summary_values)

    def test_report_date_is_latest_day_with_peak_ccu(self) -> None:
        rows = [
            PROJECT_METRICS_HEADERS.copy(),
            _row("2026-10-27", day1_retention="20%"),
            _row("2026-10-26", peak_ccu="900"),
        ]

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertEqual("2026-10-26", summary.report_date)

    def test_small_project_below_peak_ccu_floor_reports_no_alerts(self) -> None:
        rows = _rows_with_history(
            {"peak_ccu": "90", "day1_retention": "2%"},
            {"peak_ccu": "40", "day1_retention": "10%"},
        )

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertTrue(summary.below_alert_floor)
        self.assertEqual((), summary.alerts)
        self.assertEqual((("峰值PCU", "90"), ("D1", "2%")), summary.summary_values)

    def test_small_project_jumping_above_floor_still_alerts(self) -> None:
        rows = _rows_with_history({"peak_ccu": "300"}, {"peak_ccu": "50"})

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertFalse(summary.below_alert_floor)
        self.assertEqual([("peak_ccu", "rise")], [(alert.metric, alert.direction) for alert in summary.alerts])

    def test_project_falling_below_floor_still_alerts(self) -> None:
        rows = _rows_with_history({"peak_ccu": "60"}, {"peak_ccu": "300"})

        summary = build_project_trend_summary(PROJECT_ID, rows)

        self.assertFalse(summary.below_alert_floor)
        self.assertEqual([("peak_ccu", "fall")], [(alert.metric, alert.direction) for alert in summary.alerts])

    def test_empty_sheet_returns_none(self) -> None:
        self.assertIsNone(build_project_trend_summary(PROJECT_ID, [PROJECT_METRICS_HEADERS.copy()]))


if __name__ == "__main__":
    unittest.main()
