from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .github_client import GitHubClient
from .models import GameRecord
from .summary import _format_now


SPREADSHEET_TOKEN_VAR = "FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN"
TOP_TRENDING_SHEET_ID_VAR = "FEISHU_TOP_TRENDING_SHEET_ID"
UP_AND_COMING_SHEET_ID_VAR = "FEISHU_UP_AND_COMING_SHEET_ID"
CCU_BASED_SHEET_ID_VAR = "FEISHU_CCU_BASED_SHEET_ID"

SORT_SHEETS = (
    ("Top_Trending_V4", "top_trending_v4", TOP_TRENDING_SHEET_ID_VAR),
    ("Up_And_Coming_V4", "up_and_coming_v4", UP_AND_COMING_SHEET_ID_VAR),
    ("CCU_Based_V1", "ccu_based_v1", CCU_BASED_SHEET_ID_VAR),
)


@dataclass(frozen=True)
class SheetTarget:
    sort_id: str
    title: str
    variable_name: str
    sheet_id: str


@dataclass(frozen=True)
class SpreadsheetTarget:
    spreadsheet_token: str
    sheets: tuple[SheetTarget, ...]
    url: str


def build_top_trending_values(
    cfg: Config,
    sheet_title: str,
    records: list[GameRecord],
) -> list[list[str]]:
    now = _format_now(cfg.feishu_timezone)
    rows: list[list[str]] = [
        [sheet_title, "", "", "", "", "", ""],
        ["生成时间", now, "触发", _format_trigger(cfg), "条数", str(len(records)), ""],
        ["榜首", records[0].name if records else "-", "在线人数", _format_playing(records), "数据源", "Roblox Explore API", ""],
        ["", "", "", "", "", "", ""],
        ["排名", "游戏名", "在线人数", "点赞率", "总访问量", "开发者", "更新时间"],
    ]

    for record in records:
        rows.append(
            [
                str(record.rank),
                record.name,
                str(record.playing),
                format_like_rate(record.up_votes, record.down_votes),
                str(record.visits),
                record.creator or "-",
                _format_updated_at(record),
            ]
        )
    return rows


def format_like_rate(up_votes: int, down_votes: int) -> str:
    total = up_votes + down_votes
    if total <= 0:
        return "-"
    return f"{(up_votes / total) * 100:.1f}%"


def build_top_trending_summary(
    cfg: Config,
    records_by_sheet: dict[str, list[GameRecord]],
    spreadsheet_url: str,
) -> str:
    lines = [
        "Top Trending 系列表已写入飞书表格。",
        f"时间: {_format_now(cfg.feishu_timezone)} ({cfg.feishu_timezone})",
        f"触发: {_format_trigger(cfg)}",
    ]
    for _, title, _ in SORT_SHEETS:
        records = records_by_sheet.get(title, [])
        if records:
            lines.append(f"{title}: {len(records)} 条，榜首 {records[0].name} / 在线 {records[0].playing}")
        else:
            lines.append(f"{title}: 0 条")
    lines.append(f"表格: {spreadsheet_url}")
    return "\n".join(lines)


def save_spreadsheet_target(
    github_client: GitHubClient,
    target: SpreadsheetTarget,
) -> bool:
    saved = github_client.upsert_repository_variable(
        SPREADSHEET_TOKEN_VAR,
        target.spreadsheet_token,
    )
    for sheet in target.sheets:
        saved = github_client.upsert_repository_variable(sheet.variable_name, sheet.sheet_id) and saved
    return saved


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
                sheet_id=sheet_ids[variable_name],
            )
            for sort_id, title, variable_name in SORT_SHEETS
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
        }
        for sort_id, title, variable_name in SORT_SHEETS
    ]


def _format_trigger(cfg: Config) -> str:
    actor = cfg.run_trigger_actor.strip()
    if actor:
        return f"{cfg.run_trigger_source} ({actor})"
    return cfg.run_trigger_source


def _format_playing(records: list[GameRecord]) -> str:
    if not records:
        return "-"
    return str(records[0].playing)


def _format_updated_at(record: GameRecord) -> str:
    return record.updated_at or record.fetched_at
