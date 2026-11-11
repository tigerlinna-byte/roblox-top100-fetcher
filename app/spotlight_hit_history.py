"""值得关注项目的每日命中历史：记录哪些游戏当天进了“新面孔”“增长快”，用来标注连续增长天数。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, timedelta

from .daily_brief_rules import SPOTLIGHT_HIT_HISTORY_KEEP_DAYS


# 数据分支上的文件名；与游戏每日快照放在同一分支。
SPOTLIGHT_HIT_HISTORY_PATH = "spotlight_hit_history.json"
HISTORY_FORMAT_VERSION = 1
NEW_FACE_GROUP = "new_face"
GROWTH_GROUP = "growth"
_GROUPS = (NEW_FACE_GROUP, GROWTH_GROUP)

# 键为日期（ISO 格式），值为各分组当天命中的 place_id。
SpotlightHitHistory = dict[str, dict[str, frozenset[int]]]


def parse_spotlight_hit_history(raw: str) -> SpotlightHitHistory:
    """解析历史文件；格式异常时视为无历史，单条坏数据直接跳过。"""

    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    days = payload.get("days") if isinstance(payload, dict) else None
    if not isinstance(days, dict):
        return {}

    history: SpotlightHitHistory = {}
    for raw_day, raw_groups in days.items():
        try:
            day = date.fromisoformat(str(raw_day)).isoformat()
        except ValueError:
            continue
        if not isinstance(raw_groups, dict):
            continue
        history[day] = {group: _parse_place_ids(raw_groups.get(group)) for group in _GROUPS}
    return history


def merge_spotlight_hit_history(
    history: SpotlightHitHistory,
    today: date,
    new_face_place_ids: Iterable[int],
    growth_place_ids: Iterable[int],
) -> SpotlightHitHistory:
    """把当天的命中并入历史。

    与游戏每日快照一致：同一天只保留最早写入的记录，超过保留天数的被裁掉。
    """

    merged = dict(history)
    merged.setdefault(
        today.isoformat(),
        {NEW_FACE_GROUP: frozenset(new_face_place_ids), GROWTH_GROUP: frozenset(growth_place_ids)},
    )
    oldest_kept = (today - timedelta(days=SPOTLIGHT_HIT_HISTORY_KEEP_DAYS - 1)).isoformat()
    return {day: groups for day, groups in merged.items() if day >= oldest_kept}


def serialize_spotlight_hit_history(history: SpotlightHitHistory) -> str:
    """序列化为紧凑 JSON；日期从新到旧，place_id 升序，便于在数据分支上看差异。"""

    days = {
        day: {group: sorted(groups.get(group, frozenset())) for group in _GROUPS}
        for day, groups in sorted(history.items(), reverse=True)
    }
    return json.dumps({"version": HISTORY_FORMAT_VERSION, "days": days}, separators=(",", ":"))


def count_previous_growth_days(history: SpotlightHitHistory, place_id: int, today: date) -> int:
    """从昨天往前数，该游戏连续多少天在“增长快”里；中间缺一天（含当天没有记录）就停止。"""

    days = 0
    while place_id in history.get((today - timedelta(days=days + 1)).isoformat(), {}).get(GROWTH_GROUP, frozenset()):
        days += 1
    return days


def _parse_place_ids(raw: object) -> frozenset[int]:
    if not isinstance(raw, list):
        return frozenset()
    place_ids: set[int] = set()
    for item in raw:
        try:
            place_ids.add(int(item))
        except (TypeError, ValueError):
            continue
    return frozenset(place_ids)
