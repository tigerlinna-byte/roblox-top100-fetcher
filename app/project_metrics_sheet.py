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
    records: list[ProjectDailyMetricsRecord],
) -> ProjectMetricsTableState:
    """将最近窗口内的项目指标合并到已有表格中。"""

    normalized_rows = _normalize_existing_rows(existing_rows)
    for record in sorted(records, key=lambda item: item.report_date):
        _merge_single_record(normalized_rows, record)
    return ProjectMetricsTableState(rows=normalized_rows)


def _merge_single_record(rows: list[list[object]], record: ProjectDailyMetricsRecord) -> None:
    date_to_index = _build_date_index(rows)
    row_values = build_project_metrics_values(record)
    target_index = date_to_index.get(record.report_date)
    if target_index is None:
        target_index = _resolve_insert_index(rows, record.report_date)
        rows.insert(target_index, [""] * len(PROJECT_METRICS_HEADERS))

    current_row = list(rows[target_index])
    for index, value in enumerate(row_values):
        text = str(value) if value is not None else ""
        if index == 0:
            current_row[index] = text
            continue
        current_row[index] = text
    rows[target_index] = current_row


def _resolve_insert_index(rows: list[list[object]], report_date: str) -> int:
    for index, row in enumerate(rows[1:], start=1):
        current_date = str(row[0]).strip()
        if not _is_iso_date_string(current_date):
            continue
        if report_date > current_date:
            return index
    return len(rows)


def _normalize_existing_rows(existing_rows: list[list[object]]) -> list[list[object]]:
    rows: list[list[object]] = [PROJECT_METRICS_HEADERS.copy()]
    for row in existing_rows[1:] if existing_rows else []:
        normalized = [str(cell) if cell is not None else "" for cell in row[: len(PROJECT_METRICS_HEADERS)]]
        normalized.extend([""] * (len(PROJECT_METRICS_HEADERS) - len(normalized)))
        if any(str(cell).strip() for cell in normalized):
            rows.append(normalized)
    return rows


def _build_date_index(rows: list[list[object]]) -> dict[str, int]:
    return {
        str(row[0]).strip(): index
        for index, row in enumerate(rows[1:], start=1)
        if _is_iso_date_string(str(row[0]).strip())
    }


def _is_iso_date_string(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3:
        return False
    return all(part.isdigit() for part in parts) and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2
