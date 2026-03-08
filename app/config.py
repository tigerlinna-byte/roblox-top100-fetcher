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
    feishu_bot_webhook: str = ""
    feishu_timezone: str = "Asia/Shanghai"
    run_trigger_source: str = "manual"
    run_trigger_actor: str = ""


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


def load_config() -> Config:
    return Config(
        output_dir=os.getenv("OUTPUT_DIR", "./data"),
        retry_max_attempts=max(1, _get_int("RETRY_MAX_ATTEMPTS", 3)),
        retry_backoff_seconds=max(0.1, _get_float("RETRY_BACKOFF_SECONDS", 2.0)),
        request_timeout_seconds=max(1, _get_int("REQUEST_TIMEOUT_SECONDS", 15)),
        api_limit=max(1, min(100, _get_int("API_LIMIT", 100))),
        roblox_sort_id=os.getenv("ROBLOX_SORT_ID", "top-playing-now"),
        feishu_bot_webhook=os.getenv("FEISHU_BOT_WEBHOOK", ""),
        feishu_timezone=os.getenv("FEISHU_TIMEZONE", "Asia/Shanghai"),
        run_trigger_source=os.getenv("RUN_TRIGGER_SOURCE", "manual"),
        run_trigger_actor=os.getenv("RUN_TRIGGER_ACTOR", ""),
    )
