"""长线潜力：榜单游戏的每日快照历史与派生指标。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .daily_brief_rules import (
    LONG_TERM_RATING_MIN_NEW_VOTES,
    LONG_TERM_RATING_TREND_DAYS,
    LONG_TERM_TREND_COMPARE_DAYS,
    LONG_TERM_TREND_MIN_BASELINE_DAYS,
    SPOTLIGHT_MAX_CONSIDERED_RANK,
    TREND_HISTORY_KEEP_DAYS,
    TREND_HISTORY_MAX_GAME_AGE_DAYS,
)
from .models import GameRecord
from .top_trending_briefing import resolve_launch_date


# 估算单局时长时，相邻两次快照最多相隔的天数；间隔太久时日均访问不再可信。
MAX_SNAPSHOT_GAP_DAYS = 3
MINUTES_PER_DAY = 1440
HISTORY_FORMAT_VERSION = 1


@dataclass(frozen=True)
class GameDailySnapshot:
    """某款游戏某一天的快照；访问与投票都是累计值，相邻两天相减得到当日增量。"""

    snapshot_date: str
    ccu: int
    visits: int
    up_votes: int
    down_votes: int


# 键为 place_id，值按日期从新到旧排列。
GameTrendHistory = dict[int, list[GameDailySnapshot]]


@dataclass(frozen=True)
class GameTrendMetrics:
    """由快照历史计算出的长线指标；无法计算的项为 None。

    like_ratio_is_recent 为 True 表示好评率来自区间内新增投票，False 表示新增投票太少、改用累计值。
    """

    recorded_days: int
    ccu: int
    ccu_change_ratio: float | None
    peak_ratio: float | None
    board_streak_days: int
    session_minutes: float | None
    like_ratio: float | None
    like_ratio_is_recent: bool
    like_ratio_change: float | None


def build_game_daily_snapshots(
    records_by_sheet: dict[str, list[GameRecord]],
    snapshot_date: date,
) -> dict[int, GameDailySnapshot]:
    """汇总各榜单前列中较新的游戏；同一游戏出现在多个榜单时取各字段最大值（同一时刻抓取，差异很小）。"""

    snapshots: dict[int, GameDailySnapshot] = {}
    for records in records_by_sheet.values():
        for record in records:
            if record.place_id is None or record.rank > SPOTLIGHT_MAX_CONSIDERED_RANK:
                continue
            launch_date = resolve_launch_date(record)
            if launch_date is None or (snapshot_date - launch_date).days > TREND_HISTORY_MAX_GAME_AGE_DAYS:
                continue
            existing = snapshots.get(record.place_id)
            snapshots[record.place_id] = GameDailySnapshot(
                snapshot_date=snapshot_date.isoformat(),
                ccu=max(record.playing, existing.ccu if existing else 0),
                visits=max(record.visits, existing.visits if existing else 0),
                up_votes=max(record.up_votes, existing.up_votes if existing else 0),
                down_votes=max(record.down_votes, existing.down_votes if existing else 0),
            )
    return snapshots


def parse_game_trend_history(raw: str) -> GameTrendHistory:
    """解析历史文件；格式异常时视为无历史，单条坏数据直接跳过。"""

    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    games = payload.get("games") if isinstance(payload, dict) else None
    if not isinstance(games, dict):
        return {}

    history: GameTrendHistory = {}
    for raw_place_id, raw_snapshots in games.items():
        try:
            place_id = int(raw_place_id)
        except ValueError:
            continue
        if not isinstance(raw_snapshots, list):
            continue
        snapshots = [snapshot for snapshot in map(_parse_snapshot, raw_snapshots) if snapshot is not None]
        if snapshots:
            history[place_id] = sorted(snapshots, key=lambda item: item.snapshot_date, reverse=True)
    return history


def merge_game_trend_history(
    history: GameTrendHistory,
    snapshots: dict[int, GameDailySnapshot],
    snapshot_date: date,
) -> GameTrendHistory:
    """把当天快照并入历史。

    与大盘历史一致：同一天只保留最早写入的快照，保证每天快照时间固定、可互相比较；
    超过保留天数的快照被裁掉，裁完没有快照的游戏整条删除。
    """

    oldest_kept = (snapshot_date - timedelta(days=TREND_HISTORY_KEEP_DAYS - 1)).isoformat()
    merged: GameTrendHistory = {}
    for place_id in set(history) | set(snapshots):
        items = list(history.get(place_id, []))
        today = snapshots.get(place_id)
        if today is not None and all(item.snapshot_date != today.snapshot_date for item in items):
            items.append(today)
        kept = [item for item in items if item.snapshot_date >= oldest_kept]
        if kept:
            merged[place_id] = sorted(kept, key=lambda item: item.snapshot_date, reverse=True)
    return merged


def serialize_game_trend_history(history: GameTrendHistory) -> str:
    """序列化为紧凑 JSON；每条快照用数组 [日期, CCU, 访问, 点赞, 点踩] 控制文件体积。"""

    games = {
        str(place_id): [
            [item.snapshot_date, item.ccu, item.visits, item.up_votes, item.down_votes] for item in snapshots
        ]
        for place_id, snapshots in sorted(history.items())
    }
    return json.dumps({"version": HISTORY_FORMAT_VERSION, "games": games}, separators=(",", ":"))


def build_game_trend_metrics(snapshot: GameDailySnapshot, history: list[GameDailySnapshot]) -> GameTrendMetrics:
    """用当天快照与该游戏的历史计算长线指标。

    当天快照优先使用历史里已存在的同日记录，保证手动补跑时与定时快照口径一致。
    """

    snapshots_by_date = {item.snapshot_date: item for item in history}
    current = snapshots_by_date.get(snapshot.snapshot_date, snapshot)
    snapshots_by_date[current.snapshot_date] = current
    current_date = date.fromisoformat(current.snapshot_date)
    earlier = sorted(
        (item for item in snapshots_by_date.values() if item.snapshot_date < current.snapshot_date),
        key=lambda item: item.snapshot_date,
        reverse=True,
    )

    previous = earlier[0] if earlier else None
    gap_days = (current_date - date.fromisoformat(previous.snapshot_date)).days if previous else 0
    interval_previous = previous if previous is not None and gap_days <= MAX_SNAPSHOT_GAP_DAYS else None
    like_ratio, like_ratio_is_recent = _resolve_like_ratio(current, interval_previous)

    return GameTrendMetrics(
        recorded_days=len(snapshots_by_date),
        ccu=current.ccu,
        ccu_change_ratio=_ccu_change_ratio(current, earlier, current_date),
        peak_ratio=_peak_ratio(current, snapshots_by_date.values()),
        board_streak_days=_board_streak_days(snapshots_by_date, current_date),
        session_minutes=_session_minutes(current, interval_previous, gap_days),
        like_ratio=like_ratio,
        like_ratio_is_recent=like_ratio_is_recent,
        like_ratio_change=_like_ratio_change(current, earlier, current_date),
    )


def _ccu_change_ratio(
    current: GameDailySnapshot,
    earlier: list[GameDailySnapshot],
    current_date: date,
) -> float | None:
    """当天 CCU 相对之前若干天均值的变化；窗口内数据不足时不比较。"""

    window_start = (current_date - timedelta(days=LONG_TERM_TREND_COMPARE_DAYS)).isoformat()
    baseline = [item.ccu for item in earlier if item.snapshot_date >= window_start]
    if len(baseline) < LONG_TERM_TREND_MIN_BASELINE_DAYS:
        return None
    average = sum(baseline) / len(baseline)
    if average <= 0:
        return None
    return current.ccu / average - 1


def _peak_ratio(current: GameDailySnapshot, snapshots: Iterable[GameDailySnapshot]) -> float | None:
    peak = max(item.ccu for item in snapshots)
    if peak <= 0:
        return None
    return current.ccu / peak


def _board_streak_days(snapshots_by_date: dict[str, GameDailySnapshot], current_date: date) -> int:
    """从当天往前数连续有快照的天数；只有在榜前列才会记录快照，所以即连续在榜天数。"""

    streak = 0
    while (current_date - timedelta(days=streak)).isoformat() in snapshots_by_date:
        streak += 1
    return streak


def _session_minutes(
    current: GameDailySnapshot,
    previous: GameDailySnapshot | None,
    gap_days: int,
) -> float | None:
    """区间平均 CCU × 1440 ÷ 日均新增访问；访问没有增长时无法估算。"""

    if previous is None or gap_days <= 0:
        return None
    daily_visits = (current.visits - previous.visits) / gap_days
    if daily_visits <= 0:
        return None
    average_ccu = (current.ccu + previous.ccu) / 2
    return average_ccu * MINUTES_PER_DAY / daily_visits


def _resolve_like_ratio(
    current: GameDailySnapshot,
    previous: GameDailySnapshot | None,
) -> tuple[float | None, bool]:
    """优先用区间内新增投票的好评率，反映最近的口碑；新增投票太少时退回累计好评率。"""

    if previous is not None:
        new_up = current.up_votes - previous.up_votes
        new_down = current.down_votes - previous.down_votes
        if new_up >= 0 and new_down >= 0 and new_up + new_down >= LONG_TERM_RATING_MIN_NEW_VOTES:
            return new_up / (new_up + new_down), True
    return _cumulative_like_ratio(current), False


def _like_ratio_change(
    current: GameDailySnapshot,
    earlier: list[GameDailySnapshot],
    current_date: date,
) -> float | None:
    """累计好评率较若干天前（取最接近的更早快照）的变化。"""

    cutoff = (current_date - timedelta(days=LONG_TERM_RATING_TREND_DAYS)).isoformat()
    reference = next((item for item in earlier if item.snapshot_date <= cutoff), None)
    if reference is None:
        return None
    current_ratio = _cumulative_like_ratio(current)
    reference_ratio = _cumulative_like_ratio(reference)
    if current_ratio is None or reference_ratio is None:
        return None
    return current_ratio - reference_ratio


def _cumulative_like_ratio(snapshot: GameDailySnapshot) -> float | None:
    total = snapshot.up_votes + snapshot.down_votes
    if total <= 0:
        return None
    return snapshot.up_votes / total


def _parse_snapshot(entry: object) -> GameDailySnapshot | None:
    if not isinstance(entry, list) or len(entry) != 5:
        return None
    try:
        return GameDailySnapshot(
            snapshot_date=date.fromisoformat(str(entry[0])).isoformat(),
            ccu=int(entry[1]),
            visits=int(entry[2]),
            up_votes=int(entry[3]),
            down_votes=int(entry[4]),
        )
    except (TypeError, ValueError):
        return None
