from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import re

from .config import Config
from .github_client import GitHubClient
from .project_metrics_models import ProjectDailyMetricsRecord


PROJECT_METRICS_SPREADSHEET_TOKEN_VAR = "FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN"
PROJECT_METRICS_SHEET_ID_VAR = "FEISHU_PROJECT_METRICS_SHEET_ID"
PROJECT_METRICS_2_SPREADSHEET_TOKEN_VAR = "FEISHU_PROJECT_METRICS_2_SPREADSHEET_TOKEN"
PROJECT_METRICS_2_SHEET_ID_VAR = "FEISHU_PROJECT_METRICS_2_SHEET_ID"
DEFAULT_PROJECT_METRICS_SHEET_TITLE = "daily_metrics"
PROJECT_METRICS_HEADERS = [
    "日期",
    "峰值PCU",
    "平均在线时长",
    "平均在线时长同类排名",
    "次留",
    "次留同类排名",
    "7留",
    "7留同类排名",
    "付费率",
    "付费率同类排名",
    "付费用户平均收入",
    "付费用户平均收入同类排名",
    "QPTR",
    "五分钟留存",
    "Home Recommendation数量",
    "崩溃率",
    "平板内存",
    "PC内存",
    "手机内存",
    "客户端帧率",
    "服务器崩溃数",
    "服务器帧率",
    "更新时间",
]
LEGACY_PROJECT_METRICS_HEADERS = [
    "日期",
    "峰值PCU",
    "平均在线时长",
    "次留",
    "7留",
    "付费率",
    "付费用户平均收入",
    "QPTR",
    "五分钟留存",
    "Home Recommendation数量",
    "报错率",
    "更新时间",
]
PROJECT_METRICS_FIELD_TO_HEADER = {
    "report_date": "日期",
    "peak_ccu": "峰值PCU",
    "average_session_time": "平均在线时长",
    "average_session_time_rank": "平均在线时长同类排名",
    "day1_retention": "次留",
    "day1_retention_rank": "次留同类排名",
    "day7_retention": "7留",
    "day7_retention_rank": "7留同类排名",
    "payer_conversion_rate": "付费率",
    "payer_conversion_rate_rank": "付费率同类排名",
    "arppu": "付费用户平均收入",
    "arppu_rank": "付费用户平均收入同类排名",
    "qptr": "QPTR",
    "five_minute_retention": "五分钟留存",
    "home_recommendations": "Home Recommendation数量",
    "client_crash_rate": "崩溃率",
    "tablet_memory_percentage": "平板内存",
    "pc_memory_percentage": "PC内存",
    "phone_memory_percentage": "手机内存",
    "client_frame_rate": "客户端帧率",
    "server_crashes": "服务器崩溃数",
    "server_frame_rate": "服务器帧率",
    "fetched_at": "更新时间",
}
PROJECT_METRICS_HEADER_TO_FIELD = {
    header: field_name for field_name, header in PROJECT_METRICS_FIELD_TO_HEADER.items()
}
PROJECT_METRICS_HEADER_TO_FIELD["报错率"] = "client_crash_rate"
PROJECT_METRICS_LEGACY_FIELD_ORDER = (
    "report_date",
    "peak_ccu",
    "average_session_time",
    "day1_retention",
    "day7_retention",
    "payer_conversion_rate",
    "arppu",
    "qptr",
    "five_minute_retention",
    "home_recommendations",
    "client_crash_rate",
    "fetched_at",
)
PROJECT_METRICS_PERFORMANCE_FIELD_NAMES = {
    "tablet_memory_percentage",
    "pc_memory_percentage",
    "phone_memory_percentage",
    "client_frame_rate",
    "server_crashes",
    "server_frame_rate",
}
PROJECT_METRICS_RANK_FIELD_NAMES = (
    "average_session_time_rank",
    "day1_retention_rank",
    "day7_retention_rank",
    "payer_conversion_rate_rank",
    "arppu_rank",
)
PROJECT_METRICS_BACKFILL_FIELD_NAMES = tuple(
    field_name
    for field_name in PROJECT_METRICS_FIELD_TO_HEADER
    if field_name not in {"report_date", "fetched_at"}
)
PROJECT_METRICS_RANK_COLUMN_LETTERS = ("D", "F", "H", "J", "L")
PROJECT_METRICS_RANK_COLOR_STOPS = (
    (0.0, "#f54a45"),
    (25.0, "#faad14"),
    (50.0, "#7fcf7a"),
    (90.0, "#237804"),
)
PROJECT_METRICS_RANK_MAX_COLOR_VALUE = 90.0
RANK_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class ProjectMetricsSheetVariables:
    """描述项目日报表使用的 GitHub Variables 配置。"""

    project_id: str
    overview_url: str
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


@dataclass(frozen=True)
class ProjectMetricsRankColorCell:
    """描述项目日报排名单元格需要应用的字体颜色。"""

    row_index: int
    column_letter: str
    color: str


def resolve_project_metrics_variables(cfg: Config) -> tuple[ProjectMetricsSheetVariables, ...]:
    """根据运行配置解析所有启用的项目日报表变量。"""

    resolved: list[ProjectMetricsSheetVariables] = []

    primary_project_id = _extract_project_id(cfg.roblox_creator_overview_url)
    if primary_project_id:
        resolved.append(
            ProjectMetricsSheetVariables(
                project_id=primary_project_id,
                overview_url=cfg.roblox_creator_overview_url,
                spreadsheet_token_variable_name=PROJECT_METRICS_SPREADSHEET_TOKEN_VAR,
                sheet_id_variable_name=PROJECT_METRICS_SHEET_ID_VAR,
                spreadsheet_token=cfg.feishu_project_metrics_spreadsheet_token,
                sheet_id=cfg.feishu_project_metrics_sheet_id,
                spreadsheet_title=cfg.feishu_project_metrics_spreadsheet_title,
            )
        )

    secondary_project_id = _extract_project_id(cfg.roblox_creator_overview_url_2)
    if secondary_project_id:
        resolved.append(
            ProjectMetricsSheetVariables(
                project_id=secondary_project_id,
                overview_url=cfg.roblox_creator_overview_url_2,
                spreadsheet_token_variable_name=PROJECT_METRICS_2_SPREADSHEET_TOKEN_VAR,
                sheet_id_variable_name=PROJECT_METRICS_2_SHEET_ID_VAR,
                spreadsheet_token=cfg.feishu_project_metrics_2_spreadsheet_token,
                sheet_id=cfg.feishu_project_metrics_2_sheet_id,
                spreadsheet_title=cfg.feishu_project_metrics_2_spreadsheet_title,
            )
        )

    return tuple(resolved)


def build_project_metrics_spreadsheet_url(spreadsheet_token: str) -> str:
    """构造飞书表格访问地址。"""

    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def get_saved_project_metrics_target(
    cfg: Config,
    variables: ProjectMetricsSheetVariables,
) -> ProjectMetricsSpreadsheetTarget | None:
    """读取已保存的项目日报表目标。"""

    del cfg
    if not variables.spreadsheet_token or not variables.sheet_id:
        return None
    return ProjectMetricsSpreadsheetTarget(
        spreadsheet_token=variables.spreadsheet_token,
        sheet_id=variables.sheet_id,
        url=build_project_metrics_spreadsheet_url(variables.spreadsheet_token),
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
        _format_report_date_display(record.report_date),
        record.peak_ccu,
        record.average_session_time,
        record.average_session_time_rank,
        record.day1_retention,
        record.day1_retention_rank,
        record.day7_retention,
        record.day7_retention_rank,
        record.payer_conversion_rate,
        record.payer_conversion_rate_rank,
        record.arppu,
        record.arppu_rank,
        record.qptr,
        record.five_minute_retention,
        record.home_recommendations,
        record.client_crash_rate,
        record.tablet_memory_percentage,
        record.pc_memory_percentage,
        record.phone_memory_percentage,
        record.client_frame_rate,
        record.server_crashes,
        record.server_frame_rate,
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


def build_project_metrics_rebuild_rows(
    existing_rows: list[list[object]],
    records: list[ProjectDailyMetricsRecord],
    *,
    total_rows: int,
) -> list[list[object]]:
    """构建固定高度的项目日报表内容，用于整表重写并清除旧残留行。"""

    table_state = build_project_metrics_table(existing_rows, records)
    normalized_rows = [list(row) for row in table_state.rows]
    column_count = len(PROJECT_METRICS_HEADERS)
    while len(normalized_rows) < total_rows:
        normalized_rows.append([""] * column_count)
    return normalized_rows[:total_rows]


def build_project_metrics_query_dates(
    existing_rows: list[list[object]],
    start_date: date,
    end_date: date,
    *,
    max_data_rows: int,
) -> tuple[date, ...]:
    """根据已有表格内容生成需要向 Roblox 回查的日期集合。"""

    if start_date > end_date or max_data_rows <= 0:
        return ()

    normalized_rows = _normalize_existing_rows(existing_rows)
    row_by_date = {
        report_date: row
        for row in normalized_rows[1:]
        for report_date in [_extract_report_date(str(row[0]).strip())]
        if report_date is not None
    }
    candidate_dates = _build_project_metrics_candidate_dates(
        start_date,
        end_date,
        max_data_rows=max_data_rows,
    )
    query_dates: list[date] = []
    for report_date in candidate_dates:
        row = row_by_date.get(report_date.isoformat())
        if row is None or not _project_metrics_row_has_all_backfill_fields(row):
            query_dates.append(report_date)
    return tuple(sorted(query_dates))


def build_project_metrics_rank_color_cells(rows: list[list[object]]) -> list[ProjectMetricsRankColorCell]:
    """根据项目日报排名列内容构造字体颜色更新单元格。"""

    cells: list[ProjectMetricsRankColorCell] = []
    rank_columns = _resolve_project_metrics_rank_columns(rows)
    for row_index, row in enumerate(rows[1:], start=2):
        for column_index, column_letter in rank_columns:
            value = str(row[column_index]).strip() if column_index < len(row) else ""
            color = _resolve_project_metrics_rank_color(value)
            if not color:
                continue
            cells.append(
                ProjectMetricsRankColorCell(
                    row_index=row_index,
                    column_letter=column_letter,
                    color=color,
                )
            )
    return cells


def _merge_single_record(rows: list[list[object]], record: ProjectDailyMetricsRecord) -> None:
    date_to_index = _build_date_index(rows)
    row_values = build_project_metrics_values(record)
    target_index = date_to_index.get(record.report_date)
    is_new_row = False
    if target_index is None:
        target_index = _resolve_insert_index(rows, record.report_date)
        rows.insert(target_index, [""] * len(PROJECT_METRICS_HEADERS))
        is_new_row = True

    current_row = list(rows[target_index])
    filled_missing_value = False
    for index, value in enumerate(row_values):
        text = str(value) if value is not None else ""
        if index == 0:
            current_row[index] = text
            continue
        if index == len(PROJECT_METRICS_HEADERS) - 1:
            continue
        current_text = str(current_row[index]).strip() if index < len(current_row) else ""
        if text and not current_text:
            current_row[index] = text
            filled_missing_value = True
    if (is_new_row or filled_missing_value) and row_values[-1]:
        current_row[-1] = str(row_values[-1])
    rows[target_index] = current_row


def _resolve_insert_index(rows: list[list[object]], report_date: str) -> int:
    for index, row in enumerate(rows[1:], start=1):
        current_date = _extract_report_date(str(row[0]).strip())
        if current_date is None:
            continue
        if report_date > current_date:
            return index
    return len(rows)


def _normalize_existing_rows(existing_rows: list[list[object]]) -> list[list[object]]:
    rows: list[list[object]] = [PROJECT_METRICS_HEADERS.copy()]
    if not existing_rows:
        return rows

    header_row = [str(cell) if cell is not None else "" for cell in existing_rows[0]]
    for row in existing_rows[1:]:
        normalized = _normalize_existing_row(header_row, row)
        if any(cell.strip() for cell in normalized):
            rows.append(normalized)
    return rows


def _build_project_metrics_candidate_dates(
    start_date: date,
    end_date: date,
    *,
    max_data_rows: int,
) -> tuple[date, ...]:
    newest_first: list[date] = []
    current_date = end_date
    while current_date >= start_date and len(newest_first) < max_data_rows:
        newest_first.append(current_date)
        current_date -= timedelta(days=1)
    return tuple(reversed(newest_first))


def _project_metrics_row_has_all_backfill_fields(row: list[object]) -> bool:
    for field_name in PROJECT_METRICS_BACKFILL_FIELD_NAMES:
        column_index = PROJECT_METRICS_HEADERS.index(PROJECT_METRICS_FIELD_TO_HEADER[field_name])
        value = str(row[column_index]).strip() if column_index < len(row) else ""
        if not value:
            return False
    return True


def _normalize_existing_row(header_row: list[str], row: list[object]) -> list[str]:
    row_cells = [str(cell) if cell is not None else "" for cell in row]
    field_values = _extract_row_field_values(header_row, row_cells)
    normalized = [field_values.get("report_date", "")]
    for header in PROJECT_METRICS_HEADERS[1:]:
        normalized.append(field_values.get(PROJECT_METRICS_HEADER_TO_FIELD[header], ""))
    return normalized


def _extract_row_field_values(header_row: list[str], row_cells: list[str]) -> dict[str, str]:
    if _looks_like_legacy_header(header_row):
        return _extract_legacy_row_field_values(row_cells)
    if _looks_like_legacy_shifted_row(row_cells):
        return _extract_shifted_legacy_row_field_values(row_cells)
    return _extract_row_field_values_by_header(header_row, row_cells)


def _extract_row_field_values_by_header(header_row: list[str], row_cells: list[str]) -> dict[str, str]:
    field_values: dict[str, str] = {}
    for index, raw_header in enumerate(header_row):
        field_name = PROJECT_METRICS_HEADER_TO_FIELD.get(raw_header.strip(), "")
        if not field_name:
            continue
        cell_text = row_cells[index].strip() if index < len(row_cells) else ""
        normalized = _normalize_field_value(field_name, cell_text)
        if normalized:
            field_values[field_name] = normalized
    return field_values


def _extract_legacy_row_field_values(row_cells: list[str]) -> dict[str, str]:
    field_values: dict[str, str] = {}
    for index, field_name in enumerate(PROJECT_METRICS_LEGACY_FIELD_ORDER):
        cell_text = row_cells[index].strip() if index < len(row_cells) else ""
        normalized = _normalize_field_value(field_name, cell_text)
        if normalized:
            field_values[field_name] = normalized
    return field_values


def _extract_shifted_legacy_row_field_values(row_cells: list[str]) -> dict[str, str]:
    legacy_values = _extract_legacy_row_field_values(row_cells)
    current_values = _extract_row_field_values_by_header(PROJECT_METRICS_HEADERS, row_cells)
    has_current_fetched_at = bool(current_values.get("fetched_at", ""))
    field_values: dict[str, str] = {
        "report_date": legacy_values.get("report_date", current_values.get("report_date", "")),
        "peak_ccu": legacy_values.get("peak_ccu", current_values.get("peak_ccu", "")),
        "average_session_time": legacy_values.get(
            "average_session_time",
            current_values.get("average_session_time", ""),
        ),
        "day1_retention": legacy_values.get("day1_retention", ""),
        "day7_retention": current_values.get("day7_retention", legacy_values.get("day7_retention", "")),
        "payer_conversion_rate": legacy_values.get("payer_conversion_rate", ""),
        "arppu": current_values.get("arppu", legacy_values.get("arppu", "")),
        "qptr": current_values.get("qptr", legacy_values.get("qptr", "")),
        "five_minute_retention": current_values.get(
            "five_minute_retention",
            legacy_values.get("five_minute_retention", ""),
        ),
        "home_recommendations": current_values.get(
            "home_recommendations",
            legacy_values.get("home_recommendations", ""),
        ),
        "client_crash_rate": current_values.get(
            "client_crash_rate",
            legacy_values.get("client_crash_rate", ""),
        ),
        "tablet_memory_percentage": current_values.get("tablet_memory_percentage", ""),
        "pc_memory_percentage": current_values.get("pc_memory_percentage", ""),
        "phone_memory_percentage": current_values.get("phone_memory_percentage", ""),
        "client_frame_rate": current_values.get("client_frame_rate", ""),
        "server_crashes": current_values.get("server_crashes", ""),
        "server_frame_rate": current_values.get("server_frame_rate", ""),
        "fetched_at": current_values.get("fetched_at", legacy_values.get("fetched_at", "")),
    }
    for field_name in (
        "average_session_time_rank",
        "day1_retention_rank",
        "day7_retention_rank",
        "payer_conversion_rate_rank",
        "arppu_rank",
    ):
        field_values[field_name] = current_values.get(field_name, "")
    if has_current_fetched_at:
        field_values["day7_retention"] = current_values.get("day7_retention", "")
    return {field_name: value for field_name, value in field_values.items() if value}


def _resolve_project_metrics_rank_columns(rows: list[list[object]]) -> tuple[tuple[int, str], ...]:
    header_row = [str(cell).strip() if cell is not None else "" for cell in rows[0]] if rows else PROJECT_METRICS_HEADERS
    resolved_columns: list[tuple[int, str]] = []
    for field_name in PROJECT_METRICS_RANK_FIELD_NAMES:
        header = PROJECT_METRICS_FIELD_TO_HEADER[field_name]
        try:
            column_index = header_row.index(header)
        except ValueError:
            column_index = PROJECT_METRICS_HEADERS.index(header)
        resolved_columns.append((column_index, _column_letter(column_index + 1)))
    return tuple(resolved_columns)


def _resolve_project_metrics_rank_color(value: str) -> str:
    rank_value = _extract_rank_numeric_value(value)
    if rank_value is None:
        return ""
    return _interpolate_rank_color(rank_value)


def _extract_rank_numeric_value(value: str) -> float | None:
    match = RANK_NUMBER_PATTERN.search(value.strip())
    if match is None:
        return None
    return float(match.group(0))


def _interpolate_rank_color(value: float) -> str:
    bounded_value = max(0.0, min(PROJECT_METRICS_RANK_MAX_COLOR_VALUE, value))
    previous_stop = PROJECT_METRICS_RANK_COLOR_STOPS[0]
    for current_stop in PROJECT_METRICS_RANK_COLOR_STOPS[1:]:
        if bounded_value <= current_stop[0]:
            start_value, start_color = previous_stop
            end_value, end_color = current_stop
            # 相邻阈值之间按数值比例混合 RGB，避免同一档内颜色突变。
            ratio = (bounded_value - start_value) / (end_value - start_value)
            return _mix_hex_color(start_color, end_color, ratio)
        previous_stop = current_stop
    return PROJECT_METRICS_RANK_COLOR_STOPS[-1][1]


def _mix_hex_color(start_color: str, end_color: str, ratio: float) -> str:
    start_rgb = _parse_hex_color(start_color)
    end_rgb = _parse_hex_color(end_color)
    mixed_rgb = tuple(
        round(start_channel + (end_channel - start_channel) * ratio)
        for start_channel, end_channel in zip(start_rgb, end_rgb, strict=True)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed_rgb)


def _parse_hex_color(color: str) -> tuple[int, int, int]:
    normalized = color.removeprefix("#")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _looks_like_legacy_header(header_row: list[str]) -> bool:
    normalized_header = [cell.strip() for cell in header_row[: len(LEGACY_PROJECT_METRICS_HEADERS)]]
    return normalized_header == LEGACY_PROJECT_METRICS_HEADERS


def _looks_like_legacy_shifted_row(row_cells: list[str]) -> bool:
    if len(row_cells) < len(LEGACY_PROJECT_METRICS_HEADERS):
        return False
    if row_cells[3].strip() and not _looks_like_rank_text(row_cells[3].strip()):
        return True
    if row_cells[5].strip() and not _looks_like_rank_text(row_cells[5].strip()):
        return True
    if row_cells[7].strip() and not _looks_like_rank_text(row_cells[7].strip()):
        return True
    if row_cells[9].strip() and not _looks_like_rank_text(row_cells[9].strip()):
        return True
    if row_cells[11].strip() and not _looks_like_rank_text(row_cells[11].strip()):
        return True
    return False


def _normalize_field_value(field_name: str, value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if field_name == "report_date":
        report_date = _extract_report_date(text)
        return _format_report_date_display(report_date) if report_date else ""
    if field_name == "fetched_at":
        return text if _looks_like_timestamp(text) else ""
    if field_name.endswith("_rank"):
        return text if _looks_like_rank_text(text) else ""
    if field_name in {"arppu"}:
        return text if text.startswith("$") else ""
    if field_name in {
        "day1_retention",
        "day7_retention",
        "payer_conversion_rate",
        "five_minute_retention",
        "client_crash_rate",
        "tablet_memory_percentage",
        "pc_memory_percentage",
        "phone_memory_percentage",
    }:
        return text if "%" in text else ""
    if field_name in {"peak_ccu", "home_recommendations", "server_crashes"}:
        return text if _looks_like_number_text(text) else ""
    if field_name in PROJECT_METRICS_PERFORMANCE_FIELD_NAMES:
        return text
    return text


def _looks_like_timestamp(value: str) -> bool:
    return value.endswith("Z") and "T" in value


def _looks_like_rank_text(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return False
    if not text.endswith(("st", "nd", "rd", "th")):
        return False
    numeric_part = text[:-2]
    if not numeric_part:
        return False
    return numeric_part.replace(".", "", 1).isdigit()


def _looks_like_number_text(value: str) -> bool:
    text = value.strip().replace(",", "")
    return text.isdigit()


def _column_letter(index: int) -> str:
    value = max(1, index)
    letters: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _build_date_index(rows: list[list[object]]) -> dict[str, int]:
    return {
        report_date: index
        for index, row in enumerate(rows[1:], start=1)
        for report_date in [_extract_report_date(str(row[0]).strip())]
        if report_date is not None
    }


def _is_iso_date_string(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 3:
        return False
    return all(part.isdigit() for part in parts) and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2


def _extract_report_date(value: str) -> str | None:
    raw_value = value.strip()
    if not raw_value:
        return None

    date_part = raw_value.split("（", 1)[0].strip()
    if _is_iso_date_string(date_part):
        return date_part
    return None


def _format_report_date_display(report_date: str) -> str:
    parsed = date.fromisoformat(report_date)
    weekday_labels = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    return f"{report_date}（{weekday_labels[parsed.weekday()]}）"


def _extract_project_id(overview_url: str) -> str:
    parts = [part for part in overview_url.strip().split("/") if part]
    for index, part in enumerate(parts):
        if part == "experiences" and index + 1 < len(parts) and parts[index + 1].isdigit():
            return parts[index + 1]
    return ""
