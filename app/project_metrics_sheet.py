from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .github_client import GitHubClient
from .project_metrics_models import ProjectDailyMetricsRecord


PROJECT_METRICS_SPREADSHEET_TOKEN_VAR = "FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN"
PROJECT_METRICS_SHEET_ID_VAR = "FEISHU_PROJECT_METRICS_SHEET_ID"
DEFAULT_PROJECT_METRICS_SHEET_TITLE = "daily_metrics"
PROJECT_METRICS_HEADERS = [
    "日期",
    "平均CCU",
    "峰值CCU",
    "平均在线时长",
    "次留",
    "7留",
    "付费率",
    "付费用户平均收入",
    "QPTR",
    "五分钟留存",
    "Home Recommendation数量",
    "更新时间",
]


@dataclass(frozen=True)
class ProjectMetricsSheetVariables:
    """描述项目日报表使用的 GitHub Variables 配置。"""

    spreadsheet_token_variable_name: str
    sheet_id_variable_name: str
    spreadsheet_token: str
    sheet_id: str
    spreadsheet_title: str
    sheet_title: str = DEFAULT_PROJECT_METRICS_SHEET_TITLE


@dataclass(frozen=True)
class ProjectMetricsSpreadsheetTarget:
    """表示项目日报表的飞书表格目标。"""

    spreadsheet_token: str
    sheet_id: str
    url: str


@dataclass(frozen=True)
class ProjectMetricsTableState:
    """表示项目日报表当前的二维表内容。"""

    rows: list[list[object]]
    updated_row_index: int
    was_updated: bool = True


def resolve_project_metrics_variables(cfg: Config) -> ProjectMetricsSheetVariables:
    """根据运行配置解析项目日报表变量。"""

    return ProjectMetricsSheetVariables(
        spreadsheet_token_variable_name=PROJECT_METRICS_SPREADSHEET_TOKEN_VAR,
        sheet_id_variable_name=PROJECT_METRICS_SHEET_ID_VAR,
        spreadsheet_token=cfg.feishu_project_metrics_spreadsheet_token,
        sheet_id=cfg.feishu_project_metrics_sheet_id,
        spreadsheet_title=cfg.feishu_project_metrics_spreadsheet_title,
    )


def build_project_metrics_spreadsheet_url(spreadsheet_token: str) -> str:
    """构造飞书表格访问地址。"""

    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def get_saved_project_metrics_target(
    cfg: Config,
    variables: ProjectMetricsSheetVariables | None = None,
) -> ProjectMetricsSpreadsheetTarget | None:
    """读取已保存的项目日报表目标。"""

    resolved_variables = variables or resolve_project_metrics_variables(cfg)
    if not resolved_variables.spreadsheet_token or not resolved_variables.sheet_id:
        return None
    return ProjectMetricsSpreadsheetTarget(
        spreadsheet_token=resolved_variables.spreadsheet_token,
        sheet_id=resolved_variables.sheet_id,
        url=build_project_metrics_spreadsheet_url(resolved_variables.spreadsheet_token),
    )


def save_project_metrics_target(
    github_client: GitHubClient,
    target: ProjectMetricsSpreadsheetTarget,
    variables: ProjectMetricsSheetVariables,
) -> bool:
    """持久化项目日报表 token 与 sheet id。"""

    saved_token = github_client.upsert_repository_variable(
        variables.spreadsheet_token_variable_name,
        target.spreadsheet_token,
    )
    saved_sheet_id = github_client.upsert_repository_variable(
        variables.sheet_id_variable_name,
        target.sheet_id,
    )
    return saved_token and saved_sheet_id


def build_project_metrics_values(record: ProjectDailyMetricsRecord) -> list[object]:
    """将单日指标记录转成飞书表格一行。"""

    return [
        record.report_date,
        record.average_ccu,
        record.peak_ccu,
        record.average_session_time,
        record.day1_retention,
        record.day7_retention,
        record.payer_conversion_rate,
        record.arppu,
        record.qptr,
        record.five_minute_retention,
        record.home_recommendations,
        record.fetched_at,
    ]


def build_project_metrics_table(
    existing_rows: list[list[object]],
    record: ProjectDailyMetricsRecord,
) -> ProjectMetricsTableState:
    """将单日指标按日期写入已有表格内容。"""

    normalized_rows = _normalize_existing_rows(existing_rows)
    data_row = build_project_metrics_values(record)
    target_index = _find_report_date_row(normalized_rows, record.report_date)

    if target_index is not None:
        normalized_rows[target_index] = data_row
        return ProjectMetricsTableState(rows=normalized_rows, updated_row_index=target_index + 1)

    existing_dates = _extract_existing_report_dates(normalized_rows)
    if not existing_dates:
        normalized_rows.append(data_row)
        return ProjectMetricsTableState(rows=normalized_rows, updated_row_index=2)

    latest_date = existing_dates[0]
    oldest_date = existing_dates[-1]
    if record.report_date > latest_date:
        normalized_rows.insert(1, data_row)
        return ProjectMetricsTableState(rows=normalized_rows, updated_row_index=2)
    if record.report_date < oldest_date:
        return ProjectMetricsTableState(rows=normalized_rows, updated_row_index=0, was_updated=False)
    return ProjectMetricsTableState(rows=normalized_rows, updated_row_index=0, was_updated=False)


def _normalize_existing_rows(existing_rows: list[list[object]]) -> list[list[object]]:
    rows: list[list[object]] = [PROJECT_METRICS_HEADERS.copy()]
    for row in existing_rows[1:] if existing_rows else []:
        normalized = [str(cell) if cell is not None else "" for cell in row[: len(PROJECT_METRICS_HEADERS)]]
        normalized.extend([""] * (len(PROJECT_METRICS_HEADERS) - len(normalized)))
        if any(str(cell).strip() for cell in normalized):
            rows.append(normalized)
    return rows


def _extract_existing_report_dates(rows: list[list[object]]) -> list[str]:
    return [str(row[0]).strip() for row in rows[1:] if _is_iso_date_string(str(row[0]).strip())]


def _is_iso_date_string(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3:
        return False
    return all(part.isdigit() for part in parts) and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2


def _find_report_date_row(rows: list[list[object]], report_date: str) -> int | None:
    for index, row in enumerate(rows[1:], start=1):
        if str(row[0]).strip() == report_date:
            return index
    return None
