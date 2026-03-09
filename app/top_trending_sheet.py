from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .github_client import GitHubClient
from .models import GameRecord
from .summary import _format_now


SPREADSHEET_TOKEN_VAR = "FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN"
SHEET_ID_VAR = "FEISHU_TOP_TRENDING_SHEET_ID"


@dataclass(frozen=True)
class SpreadsheetTarget:
    spreadsheet_token: str
    sheet_id: str
    url: str


def build_top_trending_values(cfg: Config, records: list[GameRecord]) -> list[list[str]]:
    now = _format_now(cfg.feishu_timezone)
    rows: list[list[str]] = [
        ["Roblox Top Trending 前100", "", "", "", "", "", ""],
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


def build_top_trending_summary(cfg: Config, records: list[GameRecord], spreadsheet_url: str) -> str:
    top_line = "榜首: -"
    if records:
        top_line = f"榜首: {records[0].name} / 在线 {records[0].playing}"

    return "\n".join(
        [
            "Top Trending 前100 已写入飞书表格。",
            f"时间: {_format_now(cfg.feishu_timezone)} ({cfg.feishu_timezone})",
            f"触发: {_format_trigger(cfg)}",
            f"条数: {len(records)}",
            top_line,
            f"表格: {spreadsheet_url}",
        ]
    )


def save_spreadsheet_target(
    github_client: GitHubClient,
    target: SpreadsheetTarget,
) -> bool:
    saved_token = github_client.upsert_repository_variable(
        SPREADSHEET_TOKEN_VAR,
        target.spreadsheet_token,
    )
    saved_sheet = github_client.upsert_repository_variable(
        SHEET_ID_VAR,
        target.sheet_id,
    )
    return saved_token and saved_sheet


def get_saved_spreadsheet_target(cfg: Config) -> SpreadsheetTarget | None:
    if not cfg.feishu_top_trending_spreadsheet_token or not cfg.feishu_top_trending_sheet_id:
        return None
    return SpreadsheetTarget(
        spreadsheet_token=cfg.feishu_top_trending_spreadsheet_token,
        sheet_id=cfg.feishu_top_trending_sheet_id,
        url=build_spreadsheet_url(cfg.feishu_top_trending_spreadsheet_token),
    )


def build_spreadsheet_url(spreadsheet_token: str) -> str:
    return f"https://feishu.cn/sheets/{spreadsheet_token}"


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
