"""大盘涨跌：在玩榜总 CCU 的每日快照、历史维护与对比。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Literal

from .daily_brief_rules import (
    MARKET_CCU_HISTORY_KEEP_DAYS,
    MARKET_PULSE_BROAD_SIZE,
    MARKET_PULSE_CHANGE_THRESHOLD,
    MARKET_PULSE_DAY_COMPARE_DAYS,
    MARKET_PULSE_HEAD_SIZE,
    MARKET_PULSE_WEEK_COMPARE_DAYS,
)
from .models import GameRecord


# 保存大盘 CCU 历史的 GitHub Variable 名称。
MARKET_CCU_HISTORY_VAR = "MARKET_CCU_HISTORY"

MarketTrend = Literal["up", "down", "flat"]


@dataclass(frozen=True)
class MarketCcuSnapshot:
    """某一天在玩榜的 CCU 合计快照。"""

    snapshot_date: str
    head_ccu: int
    broad_ccu: int
    game_count: int


@dataclass(frozen=True)
class MarketChange:
    """当天快照相对某个对比日的变化。"""

    compare_date: str
    change_ratio: float
    trend: MarketTrend


@dataclass(frozen=True)
class MarketPulse:
    """早报展示用的大盘涨跌结论。"""

    snapshot: MarketCcuSnapshot
    head_day_change: MarketChange | None
    head_week_change: MarketChange | None
    broad_day_change: MarketChange | None
    broad_week_change: MarketChange | None
    recorded_days: int


def build_market_ccu_snapshot(records: list[GameRecord], snapshot_date: date) -> MarketCcuSnapshot:
    """按排名汇总头部与大盘 CCU；榜单不足 N 名时按实际条数汇总并记录条数。"""

    ranked = sorted(records, key=lambda record: record.rank)
    head_records = [record for record in ranked if record.rank <= MARKET_PULSE_HEAD_SIZE]
    broad_records = [record for record in ranked if record.rank <= MARKET_PULSE_BROAD_SIZE]
    return MarketCcuSnapshot(
        snapshot_date=snapshot_date.isoformat(),
        head_ccu=sum(record.playing for record in head_records),
        broad_ccu=sum(record.playing for record in broad_records),
        game_count=len(broad_records),
    )


def parse_market_ccu_history(raw: str) -> list[MarketCcuSnapshot]:
    """解析 GitHub Variable 中的历史，返回按日期从新到旧排列的快照；格式异常时视为无历史。"""

    if not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    entries = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []

    snapshots: list[MarketCcuSnapshot] = []
    for entry in entries:
        snapshot = _parse_snapshot(entry)
        if snapshot is not None:
            snapshots.append(snapshot)
    return sorted(snapshots, key=lambda item: item.snapshot_date, reverse=True)


def merge_market_ccu_history(
    history: list[MarketCcuSnapshot],
    snapshot: MarketCcuSnapshot,
) -> list[MarketCcuSnapshot]:
    """把当天快照并入历史。

    同一天只保留最早写入的快照：每天定时任务时间固定，保证不同日期的快照可比；
    超过保留天数的旧快照被裁掉，以控制 Variable 体积。
    """

    merged = list(history)
    if all(item.snapshot_date != snapshot.snapshot_date for item in merged):
        merged.append(snapshot)
    oldest_kept = date.fromisoformat(snapshot.snapshot_date) - timedelta(days=MARKET_CCU_HISTORY_KEEP_DAYS - 1)
    kept = [item for item in merged if date.fromisoformat(item.snapshot_date) >= oldest_kept]
    return sorted(kept, key=lambda item: item.snapshot_date, reverse=True)


def serialize_market_ccu_history(history: list[MarketCcuSnapshot]) -> str:
    """序列化为紧凑 JSON，写回 GitHub Variable。"""

    return json.dumps(
        {"history": [asdict(item) for item in history]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_market_pulse(snapshot: MarketCcuSnapshot, history: list[MarketCcuSnapshot]) -> MarketPulse:
    """用历史快照计算当天相对昨天、上周同日的涨跌。

    当天快照优先使用历史里已存在的同日记录，保证手动补跑时与定时快照口径一致。
    """

    snapshots_by_date = {item.snapshot_date: item for item in history}
    current = snapshots_by_date.get(snapshot.snapshot_date, snapshot)
    current_date = date.fromisoformat(current.snapshot_date)
    day_before = snapshots_by_date.get(
        (current_date - timedelta(days=MARKET_PULSE_DAY_COMPARE_DAYS)).isoformat()
    )
    week_before = snapshots_by_date.get(
        (current_date - timedelta(days=MARKET_PULSE_WEEK_COMPARE_DAYS)).isoformat()
    )
    recorded_dates = {item.snapshot_date for item in history} | {current.snapshot_date}
    return MarketPulse(
        snapshot=current,
        head_day_change=_build_change(current.head_ccu, day_before, "head_ccu"),
        head_week_change=_build_change(current.head_ccu, week_before, "head_ccu"),
        broad_day_change=_build_change(current.broad_ccu, day_before, "broad_ccu"),
        broad_week_change=_build_change(current.broad_ccu, week_before, "broad_ccu"),
        recorded_days=len(recorded_dates),
    )


def _build_change(
    current_value: int,
    compare_snapshot: MarketCcuSnapshot | None,
    field_name: Literal["head_ccu", "broad_ccu"],
) -> MarketChange | None:
    """计算单项变化；对比日缺失或对比值为 0 时无法比较。"""

    if compare_snapshot is None:
        return None
    compare_value = getattr(compare_snapshot, field_name)
    if compare_value <= 0:
        return None
    change_ratio = current_value / compare_value - 1
    if change_ratio >= MARKET_PULSE_CHANGE_THRESHOLD:
        trend: MarketTrend = "up"
    elif change_ratio <= -MARKET_PULSE_CHANGE_THRESHOLD:
        trend = "down"
    else:
        trend = "flat"
    return MarketChange(
        compare_date=compare_snapshot.snapshot_date,
        change_ratio=change_ratio,
        trend=trend,
    )


def _parse_snapshot(entry: object) -> MarketCcuSnapshot | None:
    if not isinstance(entry, dict):
        return None
    try:
        snapshot_date = date.fromisoformat(str(entry.get("snapshot_date", ""))).isoformat()
        return MarketCcuSnapshot(
            snapshot_date=snapshot_date,
            head_ccu=int(entry["head_ccu"]),
            broad_ccu=int(entry["broad_ccu"]),
            game_count=int(entry["game_count"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
