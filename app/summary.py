from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import Config
from .models import GameRecord


def build_success_markdown(cfg: Config, records: list[GameRecord]) -> str:
    now = _format_now(cfg.feishu_timezone)
    lines = [
        "# Roblox 排行榜同步成功",
        "",
        f"- 时间: {now} ({cfg.feishu_timezone})",
        f"- 触发: {_format_trigger(cfg)}",
        f"- 条数: {len(records)}",
    ]
    if records:
        lines.append(f"- 榜首: {records[0].name} / 在线 {records[0].playing}")
    lines.extend(["", "## Top 10"])

    for record in records[:10]:
        lines.append(
            f"{record.rank}. {record.name} | 在线 {record.playing} | 开发者 {record.creator or '-'}"
        )

    return "\n".join(lines)


def build_failure_markdown(cfg: Config, reason: str) -> str:
    now = _format_now(cfg.feishu_timezone)
    return "\n".join(
        [
            "# Roblox 排行榜任务失败",
            "",
            f"- 时间: {now} ({cfg.feishu_timezone})",
            f"- 触发: {_format_trigger(cfg)}",
            f"- 原因: {reason}",
        ]
    )


def build_project_metrics_partial_failure_markdown(
    cfg: Config,
    failed_projects: list[tuple[str, str]],
) -> str:
    """构造项目日报部分项目抓取失败的通知文案。"""

    now = _format_now(cfg.feishu_timezone)
    lines = [
        "# Roblox 项目日报抓取异常",
        "",
        f"- 时间: {now} ({cfg.feishu_timezone})",
        f"- 触发: {_format_trigger(cfg)}",
        f"- 失败项目数: {len(failed_projects)}",
        "",
        "## 失败明细",
    ]
    for project_id, reason in failed_projects:
        lines.append(f"- 项目 {project_id}: {reason}")
    return "\n".join(lines)


def _format_trigger(cfg: Config) -> str:
    actor = cfg.run_trigger_actor.strip()
    if actor:
        return f"{cfg.run_trigger_source} ({actor})"
    return cfg.run_trigger_source


def _format_now(tz_name: str) -> str:
    return datetime.now(_resolve_timezone(tz_name)).strftime("%Y-%m-%d %H:%M:%S")


def resolve_local_today(tz_name: str) -> date:
    """返回业务时区下的今天，作为早报日期与大盘快照日期。"""

    return datetime.now(_resolve_timezone(tz_name)).date()


def _resolve_timezone(tz_name: str):
    """解析时区；系统缺少时区库时，上海时区回退为固定 UTC+8，其余回退为 UTC。"""

    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        if tz_name == "Asia/Shanghai":
            return timezone(timedelta(hours=8))
        return UTC
