from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .config import Config
from .github_client import GitHubClient
from .models import GameRecord
from .top_trending_briefing import collect_top_trending_focus_place_ids_by_sheet


SPREADSHEET_TOKEN_VAR = "FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN"
TOP_TRENDING_SHEET_ID_VAR = "FEISHU_TOP_TRENDING_SHEET_ID"
UP_AND_COMING_SHEET_ID_VAR = "FEISHU_UP_AND_COMING_SHEET_ID"
TOP_PLAYING_NOW_SHEET_ID_VAR = "FEISHU_TOP_PLAYING_NOW_SHEET_ID"
TOP_TRENDING_PREV_RANKS_VAR = "FEISHU_TOP_TRENDING_PREV_RANKS"
UP_AND_COMING_PREV_RANKS_VAR = "FEISHU_UP_AND_COMING_PREV_RANKS"
TOP_PLAYING_NOW_PREV_RANKS_VAR = "FEISHU_TOP_PLAYING_NOW_PREV_RANKS"
TEST_SPREADSHEET_TOKEN_VAR = "FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN"
TEST_TOP_TRENDING_SHEET_ID_VAR = "FEISHU_TOP_TRENDING_TEST_SHEET_ID"
TEST_UP_AND_COMING_SHEET_ID_VAR = "FEISHU_UP_AND_COMING_TEST_SHEET_ID"
TEST_TOP_PLAYING_NOW_SHEET_ID_VAR = "FEISHU_TOP_PLAYING_NOW_TEST_SHEET_ID"
TEST_TOP_TRENDING_PREV_RANKS_VAR = "FEISHU_TOP_TRENDING_TEST_PREV_RANKS"
TEST_UP_AND_COMING_PREV_RANKS_VAR = "FEISHU_UP_AND_COMING_TEST_PREV_RANKS"
TEST_TOP_PLAYING_NOW_PREV_RANKS_VAR = "FEISHU_TOP_PLAYING_NOW_TEST_PREV_RANKS"

MIN_RENDER_ROWS = 140


@dataclass(frozen=True)
class SheetTarget:
    sort_id: str
    title: str
    variable_name: str
    previous_ranks_variable_name: str
    sheet_id: str


@dataclass(frozen=True)
class SpreadsheetTarget:
    spreadsheet_token: str
    sheets: tuple[SheetTarget, ...]
    url: str


@dataclass(frozen=True)
class RankChangeCell:
    row_index: int
    value: int | str
    color: str


@dataclass(frozen=True)
class LaunchDateCell:
    row_index: int
    color: str


@dataclass(frozen=True)
class GameNameHighlightCell:
    row_index: int
    color: str


@dataclass(frozen=True)
class ThumbnailCell:
    row_index: int
    url: str


@dataclass(frozen=True)
class SpreadsheetVariableSet:
    spreadsheet_token_variable_name: str
    spreadsheet_token: str
    spreadsheet_title: str
    sort_sheets: tuple[tuple[str, str, str, str], ...]
    previous_ranks_by_var: dict[str, str]


FORMAL_SORT_SHEETS = (
    ("Top_Trending_V4", "top_trending_v4", TOP_TRENDING_SHEET_ID_VAR, TOP_TRENDING_PREV_RANKS_VAR),
    ("Up_And_Coming_V4", "up_and_coming_v4", UP_AND_COMING_SHEET_ID_VAR, UP_AND_COMING_PREV_RANKS_VAR),
    ("top-playing-now", "top_playing_now", TOP_PLAYING_NOW_SHEET_ID_VAR, TOP_PLAYING_NOW_PREV_RANKS_VAR),
)
TEST_SORT_SHEETS = (
    (
        "Top_Trending_V4",
        "top_trending_v4",
        TEST_TOP_TRENDING_SHEET_ID_VAR,
        TEST_TOP_TRENDING_PREV_RANKS_VAR,
    ),
    (
        "Up_And_Coming_V4",
        "up_and_coming_v4",
        TEST_UP_AND_COMING_SHEET_ID_VAR,
        TEST_UP_AND_COMING_PREV_RANKS_VAR,
    ),
    (
        "top-playing-now",
        "top_playing_now",
        TEST_TOP_PLAYING_NOW_SHEET_ID_VAR,
        TEST_TOP_PLAYING_NOW_PREV_RANKS_VAR,
    ),
)


def resolve_spreadsheet_variables(cfg: Config) -> SpreadsheetVariableSet:
    if _should_use_formal_sheet(cfg):
        return SpreadsheetVariableSet(
            spreadsheet_token_variable_name=SPREADSHEET_TOKEN_VAR,
            spreadsheet_token=cfg.feishu_top_trending_spreadsheet_token,
            spreadsheet_title=cfg.feishu_top_trending_spreadsheet_title,
            sort_sheets=FORMAL_SORT_SHEETS,
            previous_ranks_by_var={
                TOP_TRENDING_PREV_RANKS_VAR: cfg.feishu_top_trending_prev_ranks,
                UP_AND_COMING_PREV_RANKS_VAR: cfg.feishu_up_and_coming_prev_ranks,
                TOP_PLAYING_NOW_PREV_RANKS_VAR: cfg.feishu_top_playing_now_prev_ranks,
            },
        )
    return SpreadsheetVariableSet(
        spreadsheet_token_variable_name=TEST_SPREADSHEET_TOKEN_VAR,
        spreadsheet_token=cfg.feishu_top_trending_test_spreadsheet_token,
        spreadsheet_title=cfg.feishu_top_trending_test_spreadsheet_title,
        sort_sheets=TEST_SORT_SHEETS,
        previous_ranks_by_var={
            TEST_TOP_TRENDING_PREV_RANKS_VAR: cfg.feishu_top_trending_test_prev_ranks,
            TEST_UP_AND_COMING_PREV_RANKS_VAR: cfg.feishu_up_and_coming_test_prev_ranks,
            TEST_TOP_PLAYING_NOW_PREV_RANKS_VAR: cfg.feishu_top_playing_now_test_prev_ranks,
        },
    )


def build_top_trending_values(
    cfg: Config,
    sheet_title: str,
    records: list[GameRecord],
    previous_ranks: dict[int, int],
) -> list[list[object]]:
    del cfg, sheet_title
    rows: list[list[object]] = [
        ["排名", "缩略图", "游戏名", "在线", "排名变化", "访问量", "开发者", "首次上线"],
    ]

    for record in records:
        rows.append(build_data_row(record, previous_ranks))
    return pad_rows(rows, min_rows=MIN_RENDER_ROWS, column_count=8)


def build_thumbnail_cells(records: list[GameRecord]) -> list[ThumbnailCell]:
    cells: list[ThumbnailCell] = []
    for offset, record in enumerate(records, start=2):
        thumbnail_url = record.thumbnail_url.strip()
        if thumbnail_url:
            cells.append(ThumbnailCell(row_index=offset, url=thumbnail_url))
    return cells


def build_launch_date_cells(records: list[GameRecord]) -> list[LaunchDateCell]:
    cells: list[LaunchDateCell] = []
    for offset, record in enumerate(records, start=2):
        launch_date = _format_created_at(record)
        cells.append(
            LaunchDateCell(
                row_index=offset,
                color=_resolve_launch_date_color(launch_date, record),
            )
        )
    return cells


def build_game_name_highlight_cells(
    sheet_title: str,
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> list[GameNameHighlightCell]:
    """构建需要在表格中高亮游戏名的单元格。"""

    focus_place_ids = collect_top_trending_focus_place_ids_by_sheet(
        records_by_sheet,
        previous_ranks_by_sheet,
    ).get(sheet_title, set())
    if not focus_place_ids:
        return []

    cells: list[GameNameHighlightCell] = []
    for offset, record in enumerate(records_by_sheet.get(sheet_title, []), start=2):
        if record.place_id in focus_place_ids:
            cells.append(GameNameHighlightCell(row_index=offset, color="red"))
    return cells


def build_rank_change_cells(
    records: list[GameRecord],
    previous_ranks: dict[int, int],
) -> list[RankChangeCell]:
    cells: list[RankChangeCell] = []
    for offset, record in enumerate(records, start=2):
        value = calculate_rank_change(previous_ranks, record)
        if value == "进榜":
            color = "red"
        elif isinstance(value, int) and value > 0:
            color = "red"
        elif isinstance(value, int) and value < 0:
            color = "green"
        else:
            color = "black"
        cells.append(RankChangeCell(row_index=offset, value=value, color=color))
    return cells


def calculate_rank_change(previous_ranks: dict[int, int], record: GameRecord) -> int | str:
    if not record.place_id or record.place_id not in previous_ranks:
        return "进榜"
    return previous_ranks[record.place_id] - record.rank


def build_data_row(record: GameRecord, previous_ranks: dict[int, int]) -> list[object]:
    return [
        int(record.rank),
        "",
        build_display_name(record),
        format_compact_number(record.playing),
        calculate_rank_change(previous_ranks, record),
        format_compact_number(record.visits),
        record.creator or "-",
        _format_created_at(record),
    ]


def build_display_name(record: GameRecord) -> str:
    localized_name = record.localized_name.strip()
    if not localized_name or localized_name == record.name:
        return record.name
    return f"{record.name} {localized_name}"


def pad_rows(rows: list[list[object]], *, min_rows: int, column_count: int) -> list[list[object]]:
    padded = [list(row) + [""] * (column_count - len(row)) for row in rows]
    while len(padded) < min_rows:
        padded.append([""] * column_count)
    return padded


def format_compact_number(value: int) -> str:
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if amount >= 100:
        return f"{value / 1_000:.1f}K"
    return str(value)


def calculate_game_name_width(records: list[GameRecord]) -> int:
    visual_units = max((_measure_text_units(record.name) for record in records), default=12)
    return max(240, min(960, int(visual_units * 12 + 48)))


def save_spreadsheet_target(
    github_client: GitHubClient,
    target: SpreadsheetTarget,
    variables: SpreadsheetVariableSet,
) -> bool:
    saved = github_client.upsert_repository_variable(
        variables.spreadsheet_token_variable_name,
        target.spreadsheet_token,
    )
    for sheet in target.sheets:
        saved = github_client.upsert_repository_variable(sheet.variable_name, sheet.sheet_id) and saved
    return saved


def save_previous_ranks(
    github_client: GitHubClient,
    sheet: SheetTarget,
    records: list[GameRecord],
) -> bool:
    payload = {
        str(record.place_id): record.rank
        for record in records
        if record.place_id
    }
    return github_client.upsert_repository_variable(
        sheet.previous_ranks_variable_name,
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def get_previous_ranks(cfg: Config, variables: SpreadsheetVariableSet | None = None) -> dict[str, dict[int, int]]:
    resolved_variables = variables or resolve_spreadsheet_variables(cfg)
    result: dict[str, dict[int, int]] = {}
    for _, title, _, variable_name in resolved_variables.sort_sheets:
        result[title] = _parse_previous_ranks(resolved_variables.previous_ranks_by_var.get(variable_name, ""))
    return result


def get_saved_spreadsheet_target(
    cfg: Config,
    variables: SpreadsheetVariableSet | None = None,
) -> SpreadsheetTarget | None:
    resolved_variables = variables or resolve_spreadsheet_variables(cfg)
    if not resolved_variables.spreadsheet_token:
        return None

    sheet_ids = {
        variable_name: _get_sheet_id_from_config(cfg, variable_name)
        for _, _, variable_name, _ in resolved_variables.sort_sheets
    }
    if not all(sheet_ids.values()):
        return None

    return SpreadsheetTarget(
        spreadsheet_token=resolved_variables.spreadsheet_token,
        sheets=tuple(
            SheetTarget(
                sort_id=sort_id,
                title=title,
                variable_name=variable_name,
                previous_ranks_variable_name=previous_ranks_variable_name,
                sheet_id=sheet_ids[variable_name],
            )
            for sort_id, title, variable_name, previous_ranks_variable_name in resolved_variables.sort_sheets
        ),
        url=build_spreadsheet_url(resolved_variables.spreadsheet_token),
    )


def build_spreadsheet_url(spreadsheet_token: str) -> str:
    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def build_default_sheet_specs(
    variables: SpreadsheetVariableSet | None = None,
) -> list[dict[str, str]]:
    resolved_variables = variables or SpreadsheetVariableSet(
        spreadsheet_token_variable_name=SPREADSHEET_TOKEN_VAR,
        spreadsheet_token="",
        spreadsheet_title="",
        sort_sheets=FORMAL_SORT_SHEETS,
        previous_ranks_by_var={},
    )
    return [
        {
            "sort_id": sort_id,
            "title": title,
            "variable_name": variable_name,
            "previous_ranks_variable_name": previous_ranks_variable_name,
        }
        for sort_id, title, variable_name, previous_ranks_variable_name in resolved_variables.sort_sheets
    ]


def _format_created_at(record: GameRecord) -> date | str:
    raw = record.created_at or record.updated_at or record.fetched_at
    return _short_datetime(raw)


def _resolve_launch_date_color(launch_date: date | str, record: GameRecord) -> str:
    if not isinstance(launch_date, date):
        return "black"

    reference_date = _short_datetime(record.fetched_at)
    if not isinstance(reference_date, date):
        return "black"

    age_days = max(0, (reference_date - launch_date).days)
    if age_days <= 90:
        return "green"
    if age_days <= 180:
        return "yellow"
    if age_days > 365:
        return "gray"
    return "black"


def _short_datetime(raw: str) -> date | str:
    if not raw:
        return "-"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def _parse_previous_ranks(raw: str) -> dict[int, int]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in payload.items():
        try:
            result[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _measure_text_units(text: str) -> float:
    total = 0.0
    for char in text:
        east_asian_width = unicodedata.east_asian_width(char)
        if east_asian_width in {"F", "W"}:
            total += 2.0
        elif east_asian_width == "A":
            total += 1.5
        elif char in {" ", "-", "_", ".", "'", ","}:
            total += 0.7
        else:
            total += 1.0
    return total


def _should_use_formal_sheet(cfg: Config) -> bool:
    if cfg.run_report_mode != "top_trending_sheet":
        return True
    return cfg.run_trigger_source == "cloudflare_cron"


def _get_sheet_id_from_config(cfg: Config, variable_name: str) -> str:
    values = {
        TOP_TRENDING_SHEET_ID_VAR: cfg.feishu_top_trending_sheet_id,
        UP_AND_COMING_SHEET_ID_VAR: cfg.feishu_up_and_coming_sheet_id,
        TOP_PLAYING_NOW_SHEET_ID_VAR: cfg.feishu_top_playing_now_sheet_id,
        TEST_TOP_TRENDING_SHEET_ID_VAR: cfg.feishu_top_trending_test_sheet_id,
        TEST_UP_AND_COMING_SHEET_ID_VAR: cfg.feishu_up_and_coming_test_sheet_id,
        TEST_TOP_PLAYING_NOW_SHEET_ID_VAR: cfg.feishu_top_playing_now_test_sheet_id,
    }
    return values.get(variable_name, "")
