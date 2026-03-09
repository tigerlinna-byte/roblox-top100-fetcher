from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime

from .config import Config
from .github_client import GitHubClient
from .models import GameRecord


SPREADSHEET_TOKEN_VAR = "FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN"
TOP_TRENDING_SHEET_ID_VAR = "FEISHU_TOP_TRENDING_SHEET_ID"
UP_AND_COMING_SHEET_ID_VAR = "FEISHU_UP_AND_COMING_SHEET_ID"
CCU_BASED_SHEET_ID_VAR = "FEISHU_CCU_BASED_SHEET_ID"
TOP_TRENDING_PREV_RANKS_VAR = "FEISHU_TOP_TRENDING_PREV_RANKS"
UP_AND_COMING_PREV_RANKS_VAR = "FEISHU_UP_AND_COMING_PREV_RANKS"
CCU_BASED_PREV_RANKS_VAR = "FEISHU_CCU_BASED_PREV_RANKS"

SORT_SHEETS = (
    ("Top_Trending_V4", "top_trending_v4", TOP_TRENDING_SHEET_ID_VAR, TOP_TRENDING_PREV_RANKS_VAR),
    ("Up_And_Coming_V4", "up_and_coming_v4", UP_AND_COMING_SHEET_ID_VAR, UP_AND_COMING_PREV_RANKS_VAR),
    ("CCU_Based_V1", "ccu_based_v1", CCU_BASED_SHEET_ID_VAR, CCU_BASED_PREV_RANKS_VAR),
)
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


def build_top_trending_values(
    cfg: Config,
    sheet_title: str,
    records: list[GameRecord],
    previous_ranks: dict[int, int],
) -> list[list[object]]:
    del cfg, sheet_title
    rows: list[list[object]] = [
        ["排名", "游戏名", "在线", "排名变化", "访问量", "开发者", "更新"],
    ]

    for record in records:
        rows.append(build_data_row(record, previous_ranks))
    return pad_rows(rows, min_rows=MIN_RENDER_ROWS, column_count=7)


def build_rank_change_cells(
    records: list[GameRecord],
    previous_ranks: dict[int, int],
) -> list[RankChangeCell]:
    cells: list[RankChangeCell] = []
    for offset, record in enumerate(records, start=4):
        value = calculate_rank_change(previous_ranks, record)
        if value == "-":
            color = "black"
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
        return "-"
    return previous_ranks[record.place_id] - record.rank


def build_data_row(record: GameRecord, previous_ranks: dict[int, int]) -> list[object]:
    # Keep each column's data representation stable across all data rows.
    return [
        int(record.rank),
        record.name,
        format_compact_number(record.playing),
        calculate_rank_change(previous_ranks, record),
        format_compact_number(record.visits),
        record.creator or "-",
        _format_updated_at(record),
    ]


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
    # Approximate Feishu sheet column width from visible glyph width with padding.
    return max(240, min(960, int(visual_units * 12 + 48)))


def save_spreadsheet_target(github_client: GitHubClient, target: SpreadsheetTarget) -> bool:
    saved = github_client.upsert_repository_variable(
        SPREADSHEET_TOKEN_VAR,
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


def get_previous_ranks(cfg: Config) -> dict[str, dict[int, int]]:
    raw_by_var = {
        TOP_TRENDING_PREV_RANKS_VAR: cfg.feishu_top_trending_prev_ranks,
        UP_AND_COMING_PREV_RANKS_VAR: cfg.feishu_up_and_coming_prev_ranks,
        CCU_BASED_PREV_RANKS_VAR: cfg.feishu_ccu_based_prev_ranks,
    }
    result: dict[str, dict[int, int]] = {}
    for _, title, _, variable_name in SORT_SHEETS:
        result[title] = _parse_previous_ranks(raw_by_var.get(variable_name, ""))
    return result


def get_saved_spreadsheet_target(cfg: Config) -> SpreadsheetTarget | None:
    if not cfg.feishu_top_trending_spreadsheet_token:
        return None

    sheet_ids = {
        TOP_TRENDING_SHEET_ID_VAR: cfg.feishu_top_trending_sheet_id,
        UP_AND_COMING_SHEET_ID_VAR: cfg.feishu_up_and_coming_sheet_id,
        CCU_BASED_SHEET_ID_VAR: cfg.feishu_ccu_based_sheet_id,
    }
    if not all(sheet_ids.values()):
        return None

    return SpreadsheetTarget(
        spreadsheet_token=cfg.feishu_top_trending_spreadsheet_token,
        sheets=tuple(
            SheetTarget(
                sort_id=sort_id,
                title=title,
                variable_name=variable_name,
                previous_ranks_variable_name=previous_ranks_variable_name,
                sheet_id=sheet_ids[variable_name],
            )
            for sort_id, title, variable_name, previous_ranks_variable_name in SORT_SHEETS
        ),
        url=build_spreadsheet_url(cfg.feishu_top_trending_spreadsheet_token),
    )


def build_spreadsheet_url(spreadsheet_token: str) -> str:
    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def build_default_sheet_specs() -> list[dict[str, str]]:
    return [
        {
            "sort_id": sort_id,
            "title": title,
            "variable_name": variable_name,
            "previous_ranks_variable_name": previous_ranks_variable_name,
        }
        for sort_id, title, variable_name, previous_ranks_variable_name in SORT_SHEETS
    ]


def _format_updated_at(record: GameRecord) -> date | str:
    raw = record.updated_at or record.fetched_at
    return _short_datetime(raw)


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
