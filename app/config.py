from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    output_dir: str = "./data"
    retry_max_attempts: int = 3
    retry_backoff_seconds: float = 2.0
    request_timeout_seconds: int = 15
    api_limit: int = 100
    roblox_sort_id: str = "top-playing-now"
    roblox_top_trending_sort_id: str = ""
    feishu_bot_webhook: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_timezone: str = "Asia/Shanghai"
    run_trigger_source: str = "manual"
    run_trigger_actor: str = ""
    run_chat_id: str = ""
    run_report_mode: str = "top100_message"
    github_repo_owner: str = ""
    github_repo_name: str = ""
    github_variables_token: str = ""
    feishu_top_trending_spreadsheet_token: str = ""
    feishu_top_trending_sheet_id: str = ""
    feishu_up_and_coming_sheet_id: str = ""
    feishu_ccu_based_sheet_id: str = ""
    feishu_top_trending_prev_ranks: str = ""
    feishu_up_and_coming_prev_ranks: str = ""
    feishu_ccu_based_prev_ranks: str = ""
    feishu_top_trending_spreadsheet_title: str = "Roblox Top 100"


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value)


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    return float(value)


def _split_repository_slug(value: str) -> tuple[str, str]:
    parts = [part for part in value.split("/", 1) if part]
    if len(parts) != 2:
        return "", ""
    return parts[0], parts[1]


def load_config() -> Config:
    repo_owner = os.getenv("GITHUB_REPOSITORY_OWNER", "")
    repo_name = os.getenv("GITHUB_REPOSITORY_NAME", "")
    if not repo_owner or not repo_name:
        fallback_owner, fallback_name = _split_repository_slug(os.getenv("GITHUB_REPOSITORY", ""))
        repo_owner = repo_owner or fallback_owner
        repo_name = repo_name or fallback_name

    return Config(
        output_dir=os.getenv("OUTPUT_DIR", "./data"),
        retry_max_attempts=max(1, _get_int("RETRY_MAX_ATTEMPTS", 3)),
        retry_backoff_seconds=max(0.1, _get_float("RETRY_BACKOFF_SECONDS", 2.0)),
        request_timeout_seconds=max(1, _get_int("REQUEST_TIMEOUT_SECONDS", 15)),
        api_limit=max(1, min(100, _get_int("API_LIMIT", 100))),
        roblox_sort_id=os.getenv("ROBLOX_SORT_ID", "top-playing-now"),
        roblox_top_trending_sort_id=os.getenv("ROBLOX_TOP_TRENDING_SORT_ID", ""),
        feishu_bot_webhook=os.getenv("FEISHU_BOT_WEBHOOK", ""),
        feishu_app_id=os.getenv("FEISHU_APP_ID", ""),
        feishu_app_secret=os.getenv("FEISHU_APP_SECRET", ""),
        feishu_timezone=os.getenv("FEISHU_TIMEZONE", "Asia/Shanghai"),
        run_trigger_source=os.getenv("RUN_TRIGGER_SOURCE", "manual"),
        run_trigger_actor=os.getenv("RUN_TRIGGER_ACTOR", ""),
        run_chat_id=os.getenv("RUN_CHAT_ID", ""),
        run_report_mode=os.getenv("RUN_REPORT_MODE", "top100_message"),
        github_repo_owner=repo_owner,
        github_repo_name=repo_name,
        github_variables_token=os.getenv("GITHUB_VARIABLES_TOKEN", ""),
        feishu_top_trending_spreadsheet_token=os.getenv(
            "FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN",
            "",
        ),
        feishu_top_trending_sheet_id=os.getenv("FEISHU_TOP_TRENDING_SHEET_ID", ""),
        feishu_up_and_coming_sheet_id=os.getenv("FEISHU_UP_AND_COMING_SHEET_ID", ""),
        feishu_ccu_based_sheet_id=os.getenv("FEISHU_CCU_BASED_SHEET_ID", ""),
        feishu_top_trending_prev_ranks=os.getenv("FEISHU_TOP_TRENDING_PREV_RANKS", ""),
        feishu_up_and_coming_prev_ranks=os.getenv("FEISHU_UP_AND_COMING_PREV_RANKS", ""),
        feishu_ccu_based_prev_ranks=os.getenv("FEISHU_CCU_BASED_PREV_RANKS", ""),
        feishu_top_trending_spreadsheet_title=os.getenv(
            "FEISHU_TOP_TRENDING_SPREADSHEET_TITLE",
            "Roblox Top 100",
        ),
    )
