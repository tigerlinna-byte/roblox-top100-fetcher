"""从项目日报表格内容计算早报所需的项目结论。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from .daily_brief_rules import (
    PROJECT_ALERT_METRIC_LABELS,
    PROJECT_SUMMARY_METRIC_LABELS,
    PROJECT_TREND_BASELINE_DAYS,
    PROJECT_TREND_MIN_BASELINE_DAYS,
    MetricChangeThreshold,
)
from .metric_baseline import (
    MetricAlert,
    average_baseline,
    evaluate_metric_alert,
    resolve_project_alert_thresholds,
)
from .project_metrics_sheet import PROJECT_METRICS_HEADER_TO_FIELD


# 统计日判定依据：该字段有值的最新一天才算“已出数”的统计日。
REPORT_DATE_ANCHOR_FIELD = "peak_ccu"
# 时长文本格式，例如 “1h 2m”“10m 5s”“45s”，与项目日报写表格式保持一致。
DURATION_PATTERN = re.compile(r"^(?:(?P<hours>\d+)h)?\s*(?:(?P<minutes>\d+)m)?\s*(?:(?P<seconds>\d+)s)?$")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class ProjectTrendSummary:
    """表示单个项目在早报中的结论。"""

    project_id: str
    report_date: str
    summary_values: tuple[tuple[str, str], ...]
    alerts: tuple[MetricAlert, ...]


def build_project_trend_summary(project_id: str, rows: list[list[object]]) -> ProjectTrendSummary | None:
    """根据项目日报表格内容计算统计日核心数字与超阈值提醒。

    rows 第一行是表头，其余为按日期的数据行；表格里没有任何已出数日期时返回 None。
    """

    values_by_date = _extract_values_by_date(rows)
    report_date = _resolve_report_date(values_by_date)
    if report_date is None:
        return None

    report_values = values_by_date[report_date]
    summary_values = tuple(
        (label, report_values[field_name])
        for field_name, label in PROJECT_SUMMARY_METRIC_LABELS.items()
        if report_values.get(field_name)
    )
    thresholds = resolve_project_alert_thresholds(project_id)
    alerts: list[MetricAlert] = []
    for field_name, label in PROJECT_ALERT_METRIC_LABELS.items():
        alert = _evaluate_field_alert(
            field_name,
            label,
            report_date,
            values_by_date,
            thresholds[field_name],
        )
        if alert is not None:
            alerts.append(alert)

    return ProjectTrendSummary(
        project_id=project_id,
        report_date=report_date.isoformat(),
        summary_values=summary_values,
        alerts=tuple(alerts),
    )


def parse_metric_number(text: str) -> float | None:
    """把表格里的展示文本还原成可比较的数字。

    时长统一换算为秒；百分比、货币、千分位等符号只用于展示，去掉后取数值。
    """

    normalized = text.strip()
    if not normalized:
        return None
    duration_match = DURATION_PATTERN.match(normalized)
    if duration_match and any(duration_match.groupdict().values()):
        hours = int(duration_match.group("hours") or 0)
        minutes = int(duration_match.group("minutes") or 0)
        seconds = int(duration_match.group("seconds") or 0)
        return float(hours * SECONDS_PER_HOUR + minutes * SECONDS_PER_MINUTE + seconds)
    number_match = NUMBER_PATTERN.search(normalized.replace(",", ""))
    if number_match is None:
        return None
    return float(number_match.group(0))


def _extract_values_by_date(rows: list[list[object]]) -> dict[date, dict[str, str]]:
    """按表头把每行转成 {字段名: 展示文本}，并以日期为键索引。"""

    if not rows:
        return {}
    header_fields = [PROJECT_METRICS_HEADER_TO_FIELD.get(str(cell).strip(), "") for cell in rows[0]]
    values_by_date: dict[date, dict[str, str]] = {}
    for row in rows[1:]:
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        row_values = {
            field_name: cells[index]
            for index, field_name in enumerate(header_fields)
            if field_name and index < len(cells) and cells[index]
        }
        report_date = _parse_date(row_values.get("report_date", ""))
        if report_date is not None:
            values_by_date[report_date] = row_values
    return values_by_date


def _resolve_report_date(values_by_date: dict[date, dict[str, str]]) -> date | None:
    """取核心字段已出数的最新日期作为统计日。"""

    anchored_dates = [
        report_date
        for report_date, row_values in values_by_date.items()
        if row_values.get(REPORT_DATE_ANCHOR_FIELD)
    ]
    return max(anchored_dates, default=None)


def _evaluate_field_alert(
    field_name: str,
    label: str,
    report_date: date,
    values_by_date: dict[date, dict[str, str]],
    threshold: MetricChangeThreshold,
) -> MetricAlert | None:
    """用统计日之前的窗口均值作为基线，判断单个字段是否超过阈值。"""

    current_text = values_by_date[report_date].get(field_name, "")
    current_value = parse_metric_number(current_text)
    if current_value is None:
        return None

    baseline_values = [
        value
        for offset in range(1, PROJECT_TREND_BASELINE_DAYS + 1)
        for value in (
            parse_metric_number(
                values_by_date.get(report_date - timedelta(days=offset), {}).get(field_name, "")
            ),
        )
        if value is not None
    ]
    baseline = average_baseline(baseline_values, min_count=PROJECT_TREND_MIN_BASELINE_DAYS)
    if baseline is None:
        return None
    return evaluate_metric_alert(
        metric=field_name,
        label=label,
        current_text=current_text,
        current_value=current_value,
        baseline_value=baseline,
        threshold=threshold,
    )


def _parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
