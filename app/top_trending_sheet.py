from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import Config
from .github_client import GitHubClient
from .models import GameRecord
from .summary import _format_now


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
    now = _format_now(cfg.feishu_timezone)
    rows: list[list[object]] = [
        [sheet_title, "", "", "", "", "", ""],
        ["更新", now, "触发", "feishu_chat", "条数", len(records), ""],
        ["排名", "游戏名", "在线", "排名变化", "访问量", "开发者", "更新"],
    ]

    for record in records:
        rows.append(
            [
                record.rank,
                record.name,
                format_compact_number(record.playing),
                calculate_rank_change(previous_ranks, record),
                format_compact_number(record.visits),
                record.creator or "-",
                _format_updated_at(record),
            ]
        )
    return rows


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


def format_compact_number(value: int) -> str:
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


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


def _format_updated_at(record: GameRecord) -> str:
    raw = record.updated_at or record.fetched_at
    return _short_datetime(raw)


def _short_datetime(raw: str) -> str:
    if not raw:
        return "-"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:16]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%m-%d %H:%M")


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
