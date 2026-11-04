"""长线潜力：一天多次 CCU 采样，用全天均值和近似峰值代替早报时刻的单次 CCU。

早报只在北京时间 09:10（美国晚上）取一次 CCU，以美国玩家为主的游戏会被高估，换算出的单局时长可能偏高近一倍。
一个采样窗口从上一次定时早报开始、到本次定时早报结束，与“相邻两次快照的新增访问”是同一个区间。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import json

from .daily_brief_rules import CCU_SAMPLE_EXPECTED_COUNT, CCU_SAMPLE_MIN_COUNT, CCU_SAMPLE_MIN_INTERVAL_SECONDS
from .game_trend_history import GameDailySnapshot
from .models import GameRecord


SAMPLES_FORMAT_VERSION = 1


@dataclass(frozen=True)
class CcuSampleWindow:
    """一个采样窗口。

    window_date 为开启窗口的早报日期；place_ids_by_universe 为采样名单，接口按 universe_id 查询，
    快照按 place_id 存放；ccu_by_place 只包含采样到的值，接口没有返回的游戏不补 0。
    """

    window_date: str
    place_ids_by_universe: dict[int, int]
    sampled_at: tuple[str, ...] = ()
    ccu_by_place: dict[int, tuple[int, ...]] | None = None

    @property
    def sample_count(self) -> int:
        """本窗口的总采样次数，早报自身抓到的 CCU 也算一次。"""

        return len(self.sampled_at) + 1


def build_ccu_sample_window(
    records_by_sheet: dict[str, list[GameRecord]],
    place_ids: Iterable[int],
    window_date: date,
) -> CcuSampleWindow:
    """用当天快照里的游戏开启下一窗口；只有这些游戏明天才有新增访问可以估算时长。"""

    wanted = set(place_ids)
    place_ids_by_universe = {
        record.universe_id: record.place_id
        for records in records_by_sheet.values()
        for record in records
        if record.place_id in wanted and record.universe_id
    }
    return CcuSampleWindow(window_date=window_date.isoformat(), place_ids_by_universe=place_ids_by_universe)


def parse_ccu_sample_window(raw: str) -> CcuSampleWindow | None:
    """解析采样文件；格式异常时返回 None，由下一次定时早报重新开启窗口。"""

    try:
        payload = json.loads(raw)
        return CcuSampleWindow(
            window_date=date.fromisoformat(str(payload["window_date"])).isoformat(),
            place_ids_by_universe={int(universe): int(place) for universe, place in payload["universes"].items()},
            sampled_at=tuple(str(item) for item in payload["sampled_at"]),
            ccu_by_place={
                int(place): tuple(int(value) for value in values) for place, values in payload["games"].items()
            },
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def serialize_ccu_sample_window(window: CcuSampleWindow) -> str:
    return json.dumps(
        {
            "version": SAMPLES_FORMAT_VERSION,
            "window_date": window.window_date,
            "universes": {str(universe): place for universe, place in sorted(window.place_ids_by_universe.items())},
            "sampled_at": list(window.sampled_at),
            "games": {str(place): list(values) for place, values in sorted((window.ccu_by_place or {}).items())},
        },
        separators=(",", ":"),
    )


def add_ccu_sample(window: CcuSampleWindow, ccu_by_universe: dict[int, int], sampled_at: str) -> CcuSampleWindow:
    """把一次采样并入窗口；名单之外的游戏忽略。"""

    ccu_by_place = dict(window.ccu_by_place or {})
    for universe_id, ccu in ccu_by_universe.items():
        place_id = window.place_ids_by_universe.get(universe_id)
        if place_id is not None:
            ccu_by_place[place_id] = (*ccu_by_place.get(place_id, ()), ccu)
    return replace(window, sampled_at=(*window.sampled_at, sampled_at), ccu_by_place=ccu_by_place)


def is_sampled_recently(window: CcuSampleWindow, now: str) -> bool:
    """定时任务被重复触发时，同一时段只算一次，否则采样次数虚高、时段仍然偏斜。"""

    if not window.sampled_at:
        return False
    elapsed = _parse_timestamp(now) - _parse_timestamp(window.sampled_at[-1])
    return elapsed.total_seconds() < CCU_SAMPLE_MIN_INTERVAL_SECONDS


def attach_ccu_summaries(
    snapshots: dict[int, GameDailySnapshot],
    window: CcuSampleWindow | None,
    brief_date: date,
) -> dict[int, GameDailySnapshot]:
    """把上一窗口的采样汇总进当天快照；采样不足的游戏不写均值，不用单次 CCU 代替。"""

    if not _is_previous_window(window, brief_date):
        return snapshots
    samples = window.ccu_by_place or {}
    attached: dict[int, GameDailySnapshot] = {}
    for place_id, snapshot in snapshots.items():
        values = (*samples.get(place_id, ()), snapshot.ccu)
        if len(values) < CCU_SAMPLE_MIN_COUNT:
            attached[place_id] = snapshot
            continue
        attached[place_id] = replace(
            snapshot,
            average_ccu=round(sum(values) / len(values)),
            peak_ccu=max(values),
            ccu_sample_count=len(values),
        )
    return attached


def describe_ccu_sample_problem(window: CcuSampleWindow | None, brief_date: date) -> str:
    """需要进入“数据异常”的采样问题；没有问题时返回空字符串。

    没有窗口说明采样还没开始（首次上线），当天窗口说明这是同一天的重跑，都不算异常。
    """

    if window is None or window.window_date == brief_date.isoformat():
        return ""
    if not _is_previous_window(window, brief_date):
        return f"CCU 采样窗口已过期（{window.window_date}），时长暂不计分"
    count = window.sample_count
    if count < CCU_SAMPLE_MIN_COUNT:
        return f"CCU 采样 {count}/{CCU_SAMPLE_EXPECTED_COUNT} 次，时长暂不计分"
    if count < CCU_SAMPLE_EXPECTED_COUNT:
        return f"CCU 采样 {count}/{CCU_SAMPLE_EXPECTED_COUNT} 次，时长可能有偏差"
    return ""


def _is_previous_window(window: CcuSampleWindow | None, brief_date: date) -> bool:
    """只有昨天开启的窗口才与今天的新增访问对齐；跨了更多天的采样不能代表昨天到今天这一段。"""

    return window is not None and window.window_date == (brief_date - timedelta(days=1)).isoformat()


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
