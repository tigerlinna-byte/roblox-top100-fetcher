"""行业趋势：值得关注项目（新面孔 / 增长快）与品类风向。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Literal

from .daily_brief_rules import (
    GENRE_SHARE_CHANGE_THRESHOLD,
    GENRE_SHARE_MAX_CHANGES,
    GENRE_SHARE_STABLE_TOP,
    GROWTH_BOARD_ENTRY_SHEET_KEYS,
    GROWTH_CCU_DAY_COMPARE_DAYS,
    GROWTH_CCU_DAY_EXCESS,
    GROWTH_CCU_LONG_COMPARE_DAYS,
    GROWTH_CCU_LONG_EXCESS,
    GROWTH_DETAIL_ENTRIES,
    GROWTH_EARNING_RISE_MIN_STEP,
    GROWTH_EARNING_TOP_RANK_LIMIT,
    LONG_TERM_MAX_ENTRIES,
    LONG_TERM_MIN_RECORDED_DAYS,
    LONG_TERM_SESSION_AFK_MINUTES,
    NEW_FACE_DETAIL_ENTRIES,
    NEW_FACE_GENRE_MIN_COUNT,
    NEW_FACE_GENRE_MIN_SHARE,
    NEW_FACE_LOOKBACK_DAYS,
    NEW_GAME_LEADER_STATE_THRESHOLD,
    NEW_GAME_LEADER_WEEK_COMPARE_DAYS,
    RETENTION_BAD_LIKE_RATIO,
    RETENTION_BAD_PEAK_RATIO,
    RETENTION_BAD_SESSION_MINUTES,
    RETENTION_GOOD_PEAK_RATIO,
    RETENTION_GOOD_SESSION_MINUTES,
    SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK,
    SPOTLIGHT_MAX_CONSIDERED_RANK,
    SPOTLIGHT_MAX_GAME_AGE_DAYS,
    SPOTLIGHT_MIN_CCU,
    SPOTLIGHT_NEW_GAME_LEADER_MAX_ENTRIES,
    SPOTLIGHT_NEW_GAME_LEADER_SHEET_KEY,
)
from .game_trend_history import GameDailySnapshot, GameTrendHistory, GameTrendMetrics, build_game_trend_metrics
from .market_pulse import MarketPulse
from .models import GameRecord
from .spotlight_hit_history import SpotlightHitHistory, count_previous_growth_days
from .top_trending_briefing import (
    SHEET_LABELS,
    SHEET_ORDER,
    build_briefing_display_name,
    resolve_launch_date,
    resolve_reference_date,
)


# 收入榜键：收入榜在证据判定与考察范围中有专门含义。
TOP_EARNING_SHEET_KEY = "top_earning"

# 增长证据的类别：在线涨幅、晋榜、收入榜上升。
EvidenceKind = Literal["ccu", "board_entry", "earning"]
# 留存结论：留得住、待观察、留不住。
RetentionTier = Literal["good", "watch", "bad"]
# 头部新游的势头：较上周同日上升、平稳、回落，或一周前还没上榜（新晋）。
LeaderState = Literal["up", "flat", "down", "new"]


@dataclass(frozen=True)
class EarningMovement:
    """游戏在收入榜的位置与变化；变化值为正表示排名上升。

    change 为较上次运行，上次不在榜时为 None；week_change 为较已保存历史中最早一次运行（约 7 天前），
    没有历史时为 None；entered_this_week 表示一周前不在榜，此时 week_change 按榜单末位之后一名计算。
    """

    rank: int
    change: int | None
    week_change: int | None
    entered_this_week: bool


@dataclass(frozen=True)
class RetentionVerdict:
    """留存结论及支撑它的数据，回答“这款游戏能不能留住玩家”。

    session_minutes 为估算单局时长，算不出或疑似挂机时为 None，原因见 session_note（"missing" / "afk"）；
    peak_ratio 为当前在线占 14 日峰值的比例；like_ratio 为好评率，只在偏低时用于判定留不住。
    """

    tier: RetentionTier
    session_minutes: float | None
    session_note: Literal["missing", "afk"] | None
    peak_ratio: float | None
    like_ratio: float | None


@dataclass(frozen=True)
class GrowthEvidence:
    """一条增长证据；text 是卡片上直接展示的文字。"""

    kind: EvidenceKind
    text: str


@dataclass(frozen=True)
class LeaderStatus:
    """头部新游的势头：今天与上周同日（都取每天早报那一次抓取）的在线人数。

    week_change 为原始变化比例；一周前未上榜时 ccu_week_ago、week_change 为 None，state 为 "new"。
    上周同日整天没有快照（早报没跑或快照读取失败）时 state 为 None，表示今天不判断，不用其他日期代替。
    """

    rank: int
    ccu: int
    ccu_week_ago: int | None
    week_change: float | None
    state: LeaderState | None


@dataclass(frozen=True)
class SpotlightEntry:
    """一个值得关注的游戏。

    evidence 为增长证据，新面孔没有；ccu_day_excess 为较昨天比大盘多涨的比例，无法计算时为 None。
    retention 为留存结论，快照不足 3 天时为 None。average_ccu、peak_ccu 来自一天多次采样，
    采样不足时为 None。days_on_board 为从首次上榜算起的第几天，超出回看范围时为 None。
    growth_streak_days 为连续进入“增长快”的天数（含当天）。
    """

    place_id: int
    name: str
    genre: str
    ccu: int
    sheet_ranks: tuple[tuple[str, int], ...]
    age_days: int | None = None
    evidence: tuple[GrowthEvidence, ...] = ()
    ccu_day_excess: float | None = None
    retention: RetentionVerdict | None = None
    earning: EarningMovement | None = None
    universe_id: int | None = None
    average_ccu: int | None = None
    peak_ccu: int | None = None
    ccu_sample_count: int = 0
    days_on_board: int | None = None
    growth_streak_days: int = 0
    leader: LeaderStatus | None = None


@dataclass(frozen=True)
class MarketSpotlight:
    """早报中的值得关注项目，各栏互不重复。

    新面孔：最近若干天没上过榜的新游，按 CCU 排序；增长快：有增长证据的新游，按证据条数、在线涨幅排序。
    两栏各有一款“今日最突出”，其后是卡片上详细展示的条目；overflow 是排名靠后、卡片不展示的其余命中游戏，
    只写入明细产物，并参与命中历史（连续增长天数）。
    long_term 为留得住、且没有在两栏卡片上展示的新游，按单局时长排序；new_game_leaders 为在玩榜排名最高的几款新游及其势头，
    不和其他栏去重，保证每天看的是同一批头部游戏。
    new_face_lookback_days 为实际能回看的天数（0 表示当天无法判断新面孔）；
    problems 为历史数据缺失导致的未判断项，由调用方写入“数据异常”。
    before_scheduled_snapshot 为 True 表示手动运行早于当天的定时早报：当天的快照还没存下，此刻抓到的数据
    与各天 09:10 的快照不是同一时刻，相减也不足一天，所以留存结论与头部新游趋势都不判断，以定时早报为准。
    """

    new_face_standout: SpotlightEntry | None = None
    new_faces: tuple[SpotlightEntry, ...] = ()
    new_face_overflow: tuple[SpotlightEntry, ...] = ()
    growth_standout: SpotlightEntry | None = None
    growth: tuple[SpotlightEntry, ...] = ()
    growth_overflow: tuple[SpotlightEntry, ...] = ()
    long_term: tuple[SpotlightEntry, ...] = ()
    long_term_recorded_days: int = 0
    new_game_leaders: tuple[SpotlightEntry, ...] = ()
    new_face_lookback_days: int = 0
    problems: tuple[str, ...] = ()
    before_scheduled_snapshot: bool = False

    @property
    def all_new_faces(self) -> tuple[SpotlightEntry, ...]:
        """当天全部新面孔，含最突出与卡片不展示的。"""

        standout = (self.new_face_standout,) if self.new_face_standout is not None else ()
        return (*standout, *self.new_faces, *self.new_face_overflow)

    @property
    def all_growth(self) -> tuple[SpotlightEntry, ...]:
        """当天全部增长快的游戏，含最突出与卡片不展示的。"""

        standout = (self.growth_standout,) if self.growth_standout is not None else ()
        return (*standout, *self.growth, *self.growth_overflow)


@dataclass(frozen=True)
class _CandidateGame:
    """聚合同一游戏在各榜单中的表现。"""

    best_record: GameRecord
    ranks_by_sheet: dict[str, int]
    ccu: int


class _TrendView:
    """按日期查询游戏快照与大盘 CCU，统一处理“当天”和“若干天前”的取数。

    history 为 None 表示快照读取失败。对比日必须恰好是指定的那一天，缺失时返回 None，
    不用相邻日期代替。
    """

    def __init__(
        self,
        today: date,
        snapshots: dict[int, GameDailySnapshot] | None,
        history: GameTrendHistory | None,
        market_ccu_by_date: dict[str, int] | None,
    ) -> None:
        self.today = today
        self.history = history
        self._snapshots = snapshots or {}
        self._market = market_ccu_by_date or {}
        self._by_date: dict[int, dict[str, GameDailySnapshot]] = {
            place_id: {item.snapshot_date: item for item in items} for place_id, items in (history or {}).items()
        }
        self._lookback_dates = {self._date(offset) for offset in range(1, NEW_FACE_LOOKBACK_DAYS + 1)}
        self._recorded_dates = {day for by_date in self._by_date.values() for day in by_date}

    def _date(self, days_ago: int) -> str:
        return (self.today - timedelta(days=days_ago)).isoformat()

    @property
    def lookback_days(self) -> int:
        """回看窗口内实际有快照的天数；0 表示无法判断新面孔。"""

        return len(self._recorded_dates & self._lookback_dates)

    def is_new_face(self, place_id: int) -> bool:
        return not (self._lookback_dates & set(self._by_date.get(place_id, {})))

    def days_on_board(self, place_id: int) -> int | None:
        """从回看窗口内第一次有快照算起，今天是第几天；窗口最早一天就在榜时无法确定，返回 None。"""

        earlier = self._lookback_dates & set(self._by_date.get(place_id, {}))
        if not earlier:
            return 1
        first_seen = min(earlier)
        if first_seen == self._date(NEW_FACE_LOOKBACK_DAYS):
            return None
        return (self.today - date.fromisoformat(first_seen)).days + 1

    def game_history(self, place_id: int) -> list[GameDailySnapshot]:
        return list(self._by_date.get(place_id, {}).values())

    def snapshot(self, place_id: int) -> GameDailySnapshot | None:
        return self._snapshots.get(place_id)

    def ccu(self, place_id: int, days_ago: int = 0) -> int | None:
        """某天的 CCU；当天优先用历史里已有的同日快照，保证手动补跑时与定时快照口径一致。"""

        stored = self._by_date.get(place_id, {}).get(self._date(days_ago))
        if stored is not None:
            return stored.ccu
        if days_ago == 0 and place_id in self._snapshots:
            return self._snapshots[place_id].ccu
        return None

    def has_snapshot_day(self, days_ago: int) -> bool:
        """那一天是否有游戏快照（任何一款都算）；没有说明当天早报没跑或数据缺失。"""

        return self._date(days_ago) in self._recorded_dates

    def has_comparison(self, days_ago: int) -> bool:
        """对比日是否同时有游戏快照和大盘快照。"""

        return (
            self._date(days_ago) in self._recorded_dates
            and self._market.get(self._date(0), 0) > 0
            and self._market.get(self._date(days_ago), 0) > 0
        )

    def change(self, place_id: int, days_ago: int) -> float | None:
        """在线较若干天前的原始变化比例。"""

        current, earlier = self.ccu(place_id), self.ccu(place_id, days_ago)
        if current is None or not earlier:
            return None
        return current / earlier - 1

    def excess(self, place_id: int, days_ago: int) -> float | None:
        """在线较若干天前比大盘多涨的比例：游戏涨幅除以大盘涨幅再减一。"""

        change = self.change(place_id, days_ago)
        if change is None or not self.has_comparison(days_ago):
            return None
        market_ratio = self._market[self._date(0)] / self._market[self._date(days_ago)]
        return (1 + change) / market_ratio - 1


def build_market_spotlight(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    recent_place_ids_by_sheet: dict[str, set[int]],
    trend_snapshots: dict[int, GameDailySnapshot] | None = None,
    trend_history: GameTrendHistory | None = None,
    oldest_ranks_by_sheet: dict[str, dict[int, int]] | None = None,
    market_ccu_by_date: dict[str, int] | None = None,
    hit_history: SpotlightHitHistory | None = None,
    brief_date: date | None = None,
) -> MarketSpotlight:
    """把各榜单里的新游分成“新面孔”“增长快”等栏目。

    previous_ranks_by_sheet 为上一次运行的排名，recent_place_ids_by_sheet 为最近若干次运行出现过的游戏，
    两者用于判断晋榜与收入榜上升；oldest_ranks_by_sheet 为已保存历史中最早一次运行的排名。
    trend_snapshots 为当天的游戏快照，trend_history 为此前的每日快照（None 表示读取失败），
    用于判断新面孔、在线涨幅与长线指标；market_ccu_by_date 为大盘每天的 CCU 合计，用来扣除大盘涨跌。
    hit_history 为此前每天的命中记录，用于标注连续增长天数；brief_date 为早报日期，缺省时取抓取日期。
    """

    reference_date = resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return MarketSpotlight()

    today = brief_date or reference_date
    view = _TrendView(today, trend_snapshots, trend_history, market_ccu_by_date)
    can_judge_new_faces = view.lookback_days > 0
    # 定时早报会先把当天快照存进历史；历史里有往日快照却没有当天的，说明是早于当天定时早报的手动运行。
    # 这时此刻的在线、访问与各天 09:10 的快照不是同一时刻（例如凌晨 1 点与昨天 9 点相减只有 16 小时，
    # 单局时长会被放大一半），所以不做留存结论和头部新游趋势这类跨天对比。
    before_scheduled_snapshot = can_judge_new_faces and not view.has_snapshot_day(0)
    oldest_ranks = oldest_ranks_by_sheet or {}

    new_faces: list[SpotlightEntry] = []
    growth: list[SpotlightEntry] = []
    steady: list[SpotlightEntry] = []
    leader_candidates: list[SpotlightEntry] = []
    long_term_recorded_days = 0
    for place_id, candidate in _collect_candidates(records_by_sheet, reference_date).items():
        age_days = _resolve_age_days(candidate.best_record, reference_date)
        # 只看新游；上线时间未知的游戏无法判断是不是新游，同样跳过。
        if age_days is None or age_days > SPOTLIGHT_MAX_GAME_AGE_DAYS or candidate.ccu < SPOTLIGHT_MIN_CCU:
            continue
        earning = _build_earning_movement(
            place_id,
            candidate,
            previous_ranks_by_sheet,
            oldest_ranks.get(TOP_EARNING_SHEET_KEY, {}),
        )
        entry = _build_entry(place_id, candidate, age_days, earning)

        metrics = None if before_scheduled_snapshot else _build_metrics(view, place_id)
        if metrics is not None:
            long_term_recorded_days = max(long_term_recorded_days, metrics.recorded_days)
            entry = replace(
                entry,
                retention=_judge_retention(metrics),
                average_ccu=metrics.average_ccu,
                peak_ccu=metrics.peak_ccu,
                ccu_sample_count=metrics.ccu_sample_count,
            )
        if can_judge_new_faces:
            entry = replace(entry, days_on_board=view.days_on_board(place_id))
        leader = _build_leader_status(view, place_id, candidate, judge_trend=not before_scheduled_snapshot)
        if leader is not None:
            leader_candidates.append(replace(entry, leader=leader))

        if can_judge_new_faces and view.is_new_face(place_id):
            new_faces.append(entry)
            continue
        ccu_evidence, day_excess = _build_ccu_evidence(view, place_id)
        evidence = (
            *ccu_evidence,
            *_build_board_entry_evidence(place_id, candidate, recent_place_ids_by_sheet),
            *_build_earning_evidence(place_id, earning, previous_ranks_by_sheet, recent_place_ids_by_sheet),
        )
        entry = replace(entry, evidence=evidence, ccu_day_excess=day_excess)
        if evidence:
            streak = count_previous_growth_days(hit_history or {}, place_id, today) + 1
            growth.append(replace(entry, growth_streak_days=streak))
        else:
            steady.append(entry)

    new_faces.sort(key=lambda entry: (-entry.ccu, entry.name.casefold()))
    growth.sort(key=_growth_sort_key)
    new_face_shown = new_faces[:NEW_FACE_DETAIL_ENTRIES]
    growth_shown = growth[:GROWTH_DETAIL_ENTRIES]
    shown_place_ids = {entry.place_id for entry in (*new_face_shown, *growth_shown)}
    # 长线潜力：留得住、且卡片上还没展示的新游；排名靠后没上卡片的增长快游戏也可以在这里露面。没有就不硬凑。
    long_term = sorted(
        (
            entry
            for entry in (*new_faces, *growth, *steady)
            if entry.place_id not in shown_place_ids and entry.retention is not None and entry.retention.tier == "good"
        ),
        key=lambda entry: (-(entry.retention.session_minutes or 0), -entry.ccu, entry.name.casefold()),
    )[:LONG_TERM_MAX_ENTRIES]
    # 头部新游趋势固定取在玩榜排名最高的几款新游，不和其他栏去重，名单才不会时有时无。
    leaders = sorted(leader_candidates, key=lambda entry: entry.leader.rank)[:SPOTLIGHT_NEW_GAME_LEADER_MAX_ENTRIES]
    problems = _describe_trend_problems(view)
    if (
        view.history is not None
        and not before_scheduled_snapshot
        and any(entry.leader.state is None for entry in leaders)
    ):
        problems += (
            f"缺少 {NEW_GAME_LEADER_WEEK_COMPARE_DAYS} 天前（上周同日）的快照，今天不判断头部新游趋势",
        )

    return MarketSpotlight(
        new_face_standout=new_faces[0] if new_faces else None,
        new_faces=tuple(new_faces[1:NEW_FACE_DETAIL_ENTRIES]),
        new_face_overflow=tuple(new_faces[NEW_FACE_DETAIL_ENTRIES:]),
        growth_standout=growth[0] if growth else None,
        growth=tuple(growth[1:GROWTH_DETAIL_ENTRIES]),
        growth_overflow=tuple(growth[GROWTH_DETAIL_ENTRIES:]),
        long_term=tuple(long_term),
        long_term_recorded_days=long_term_recorded_days,
        new_game_leaders=tuple(leaders),
        new_face_lookback_days=view.lookback_days,
        problems=problems,
        before_scheduled_snapshot=before_scheduled_snapshot,
    )


@dataclass(frozen=True)
class NewGameGenreCounts:
    """新游各品类款数与新游总款数；总款数含未标品类的游戏，是品类占比的分母。"""

    counts: dict[str, int]
    total: int


def build_new_game_genre_counts(records_by_sheet: dict[str, list[GameRecord]]) -> NewGameGenreCounts:
    """新游各品类的款数，范围与值得关注项目一致；榜单没有抓取日期时为空。"""

    reference_date = resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return NewGameGenreCounts({}, 0)
    genres = _collect_new_game_genres(records_by_sheet, reference_date)
    return NewGameGenreCounts(dict(Counter(genre for genre in genres if genre)), len(genres))


def build_genre_wind_lines(
    records_by_sheet: dict[str, list[GameRecord]],
    new_face_genres: Iterable[str] | None,
    pulse: MarketPulse | None = None,
) -> tuple[str, ...]:
    """品类风向：新面孔明显集中的品类；新游各品类款数占比与自身历史（昨天、上周同日）的比较。

    new_face_genres 为当天全部新面孔的品类，与新面孔栏口径一致；None 表示当天无法判断新面孔。
    """

    lines: list[str] = []
    cluster = _new_face_genre_cluster(list(new_face_genres or ()))
    if cluster:
        lines.append(cluster)
    share_line = _build_genre_share_line(build_new_game_genre_counts(records_by_sheet), pulse)
    if share_line:
        lines.append(share_line)
    return tuple(lines)


def _collect_new_game_genres(records_by_sheet: dict[str, list[GameRecord]], reference_date: date) -> list[str]:
    """值得关注项目范围内每款新游的品类（未标品类为空串）：四个榜单考察范围内、创建不超过上限天数、CCU 达到下限。"""

    genres: list[str] = []
    for candidate in _collect_candidates(records_by_sheet, reference_date).values():
        age_days = _resolve_age_days(candidate.best_record, reference_date)
        if age_days is None or age_days > SPOTLIGHT_MAX_GAME_AGE_DAYS or candidate.ccu < SPOTLIGHT_MIN_CCU:
            continue
        genres.append(candidate.best_record.genre.strip())
    return genres


def _genre_permille(counts: dict[str, int], total: int) -> dict[str, int]:
    """各品类款数占比（千分比）；总款数为 0 时为空。"""

    if total <= 0:
        return {}
    return {genre: round(count * 1000 / total) for genre, count in counts.items() if count > 0}


def _new_face_genre_cluster(genres: list[str]) -> str:
    """新面孔明显集中在某个品类时才写，例如“今日新面孔 14 款中 5 款是 Tycoon”。"""

    counter = Counter(genre for genre in genres if genre)
    if not counter:
        return ""
    genre, count = counter.most_common(1)[0]
    if count < NEW_FACE_GENRE_MIN_COUNT or count / len(genres) < NEW_FACE_GENRE_MIN_SHARE:
        return ""
    return f"今日新面孔 {len(genres)} 款中 {count} 款是 {genre}"


def _build_genre_share_line(current_counts: NewGameGenreCounts, pulse: MarketPulse | None) -> str:
    """新游各品类款数占比与自身历史比较。

    先看较昨天、再看较上周同日，占比变化达到门槛的品类写出变化；都没有明显变化时列占比前几名，
    各附上历史占比作参照（优先上周同日）；完全没有历史时如实写“历史数据积累中”，不拿其他数据当参照。
    按款数而不是 CCU 算，一款游戏在线暴涨或掉出榜单最多只影响一款的占比。
    """

    current = _genre_permille(current_counts.counts, current_counts.total)
    if not current:
        return ""
    compare_snapshots = (
        ("昨天", pulse.day_before if pulse else None),
        ("上周同日", pulse.week_before if pulse else None),
    )
    references: list[tuple[str, dict[str, int]]] = []
    for compare_label, compare_snapshot in compare_snapshots:
        if compare_snapshot is None or compare_snapshot.new_game_count <= 0:
            continue
        previous = _genre_permille(compare_snapshot.new_game_genre_counts, compare_snapshot.new_game_count)
        references.append((compare_label, previous))
        changes = sorted(
            ((genre, previous.get(genre, 0), current.get(genre, 0)) for genre in set(current) | set(previous)),
            # 幅度相同时上升的品类在前，更值得关注。
            key=lambda item: (-abs(item[2] - item[1]), item[1] - item[2], item[0]),
        )
        significant = [
            item for item in changes if abs(item[2] - item[1]) >= GENRE_SHARE_CHANGE_THRESHOLD * 1000
        ][:GENRE_SHARE_MAX_CHANGES]
        if significant:
            parts = [
                _format_genre_share_change(genre, before, after, current_counts.counts.get(genre, 0))
                for genre, before, after in significant
            ]
            return f"新游款数占比较{compare_label}变化：" + "、".join(parts)

    top_genres = sorted(
        current_counts.counts.items(), key=lambda item: (-item[1], item[0])
    )[:GENRE_SHARE_STABLE_TOP]
    if not references:
        return f"新游款数占比前 {len(top_genres)}：" + "、".join(
            f"{genre} {count} 款 {_format_permille(current[genre])}" for genre, count in top_genres
        ) + "（历史数据积累中，暂不判断多少）"
    # 有上周同日时用上周同日作参照（同一个星期几，抵消周末效应），否则用昨天。
    reference_label, reference = references[-1]
    return f"新游格局稳定，款数占比前 {len(top_genres)}：" + "、".join(
        f"{genre} {count} 款 {_format_permille(current[genre])}"
        f"（{reference_label} {_format_permille(reference.get(genre, 0))}）"
        for genre, count in top_genres
    )


def _format_genre_share_change(genre: str, before: int, after: int, count_now: int) -> str:
    """例如“Tycoon 12% → 18%（+6 个百分点，现 28 款）”。"""

    # 用展示出来的两个百分比相减，避免“3% → 24%（+20）”这类分别取整造成的对不上。
    delta_points = round(after / 10) - round(before / 10)
    return f"{genre} {_format_permille(before)} → {_format_permille(after)}（{delta_points:+d} 个百分点，现 {count_now} 款）"


def _format_permille(permille: int) -> str:
    return f"{round(permille / 10)}%"


def _collect_candidates(
    records_by_sheet: dict[str, list[GameRecord]],
    reference_date: date,
) -> dict[int, _CandidateGame]:
    """把各榜单前列记录按游戏聚合，记录每个榜单的排名与最高 CCU。

    收入榜对新游放宽到更靠后的名次，用来发现刚开始变现的游戏。
    """

    candidates: dict[int, _CandidateGame] = {}
    for sheet_key in SHEET_ORDER:
        for record in records_by_sheet.get(sheet_key, []):
            if record.place_id is None or record.rank > _considered_rank_limit(sheet_key, record, reference_date):
                continue
            existing = candidates.get(record.place_id)
            if existing is None:
                candidates[record.place_id] = _CandidateGame(
                    best_record=record,
                    ranks_by_sheet={sheet_key: record.rank},
                    ccu=record.playing,
                )
                continue
            existing.ranks_by_sheet[sheet_key] = record.rank
            candidates[record.place_id] = _CandidateGame(
                best_record=record if record.rank < existing.best_record.rank else existing.best_record,
                ranks_by_sheet=existing.ranks_by_sheet,
                ccu=max(existing.ccu, record.playing),
            )
    return candidates


def _considered_rank_limit(sheet_key: str, record: GameRecord, reference_date: date) -> int:
    if sheet_key != TOP_EARNING_SHEET_KEY:
        return SPOTLIGHT_MAX_CONSIDERED_RANK
    age_days = _resolve_age_days(record, reference_date)
    if age_days is None or age_days > SPOTLIGHT_MAX_GAME_AGE_DAYS:
        return SPOTLIGHT_MAX_CONSIDERED_RANK
    return SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK


def _resolve_age_days(record: GameRecord, reference_date: date) -> int | None:
    launch_date = resolve_launch_date(record)
    if launch_date is None:
        return None
    return (reference_date - launch_date).days


def _build_entry(
    place_id: int,
    candidate: _CandidateGame,
    age_days: int,
    earning: EarningMovement | None,
) -> SpotlightEntry:
    return SpotlightEntry(
        place_id=place_id,
        name=build_briefing_display_name(candidate.best_record),
        genre=candidate.best_record.genre.strip(),
        ccu=candidate.ccu,
        sheet_ranks=tuple(
            (SHEET_LABELS[sheet_key], candidate.ranks_by_sheet[sheet_key])
            for sheet_key in SHEET_ORDER
            if sheet_key in candidate.ranks_by_sheet
        ),
        age_days=age_days,
        earning=earning,
        universe_id=candidate.best_record.universe_id,
    )


def _build_metrics(view: _TrendView, place_id: int) -> GameTrendMetrics | None:
    """长线指标；快照读取失败或当天没有该游戏的快照时为 None。"""

    snapshot = view.snapshot(place_id)
    if snapshot is None or view.history is None:
        return None
    return build_game_trend_metrics(snapshot, view.game_history(place_id))


def _describe_trend_problems(view: _TrendView) -> tuple[str, ...]:
    """历史数据缺失时说明当天哪些判断没有做；不拿其他日期或数据源顶替。"""

    if view.history is None:
        return ("游戏每日快照读取失败，今天不判断新面孔、在线涨幅和长线潜力",)
    if view.lookback_days == 0:
        return ("还没有可用的历史快照，今天不判断新面孔和在线涨幅",)
    problems: list[str] = []
    if not view.has_comparison(GROWTH_CCU_DAY_COMPARE_DAYS):
        problems.append("缺少昨天的游戏或大盘快照，今天不判断较昨天的在线涨幅")
    if not view.has_comparison(GROWTH_CCU_LONG_COMPARE_DAYS):
        problems.append(
            f"缺少 {GROWTH_CCU_LONG_COMPARE_DAYS} 天前的游戏或大盘快照，"
            f"今天不判断较 {GROWTH_CCU_LONG_COMPARE_DAYS} 天前的在线涨幅"
        )
    return tuple(problems)


def _build_ccu_evidence(view: _TrendView, place_id: int) -> tuple[tuple[GrowthEvidence, ...], float | None]:
    """在线证据：较昨天比大盘多涨达到门槛，否则再看较若干天前；同时返回较昨天的超额涨幅用于排序。"""

    day_excess = view.excess(place_id, GROWTH_CCU_DAY_COMPARE_DAYS)
    if day_excess is not None and day_excess >= GROWTH_CCU_DAY_EXCESS:
        return (GrowthEvidence("ccu", f"在线比大盘多涨 {day_excess:.0%}（较昨天）"),), day_excess
    long_excess = view.excess(place_id, GROWTH_CCU_LONG_COMPARE_DAYS)
    if long_excess is not None and long_excess >= GROWTH_CCU_LONG_EXCESS:
        text = f"在线比大盘多涨 {long_excess:.0%}（较 {GROWTH_CCU_LONG_COMPARE_DAYS} 天前）"
        return (GrowthEvidence("ccu", text),), day_excess
    return (), day_excess


def _build_board_entry_evidence(
    place_id: int,
    candidate: _CandidateGame,
    recent_place_ids_by_sheet: dict[str, set[int]],
) -> tuple[GrowthEvidence, ...]:
    """晋榜证据：最近若干次运行首次进入热门榜、在玩榜前列。

    某个榜单没有历史时无法判断，不能把整张榜都当成新进榜。收入榜的晋榜归入收入证据。
    """

    entered = [
        SHEET_LABELS[sheet_key]
        for sheet_key in GROWTH_BOARD_ENTRY_SHEET_KEYS
        if candidate.ranks_by_sheet.get(sheet_key, SPOTLIGHT_MAX_CONSIDERED_RANK + 1) <= SPOTLIGHT_MAX_CONSIDERED_RANK
        and recent_place_ids_by_sheet.get(sheet_key)
        and place_id not in recent_place_ids_by_sheet[sheet_key]
    ]
    if not entered:
        return ()
    return (GrowthEvidence("board_entry", f"新进{'、'.join(entered)}"),)


def _build_earning_evidence(
    place_id: int,
    earning: EarningMovement | None,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    recent_place_ids_by_sheet: dict[str, set[int]],
) -> tuple[GrowthEvidence, ...]:
    """收入证据：首次进入收入榜考察范围、较上次上升达到步长，或冲进前列。

    收入榜没有历史时不判断，避免首次运行把所有游戏都当成新进榜。
    """

    recent_place_ids = recent_place_ids_by_sheet.get(TOP_EARNING_SHEET_KEY)
    if earning is None or not recent_place_ids or not previous_ranks_by_sheet.get(TOP_EARNING_SHEET_KEY):
        return ()
    label = SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    if place_id not in recent_place_ids:
        return (GrowthEvidence("earning", f"新进{label}"),)
    if earning.change is not None and earning.change >= GROWTH_EARNING_RISE_MIN_STEP:
        return (GrowthEvidence("earning", f"{label} ↑{earning.change}"),)
    previous_rank = earning.rank + earning.change if earning.change is not None else None
    if earning.rank <= GROWTH_EARNING_TOP_RANK_LIMIT and (
        previous_rank is None or previous_rank > GROWTH_EARNING_TOP_RANK_LIMIT
    ):
        return (GrowthEvidence("earning", f"冲进{label}前 {GROWTH_EARNING_TOP_RANK_LIMIT}"),)
    return ()


def _growth_sort_key(entry: SpotlightEntry) -> tuple[int, float, int, str]:
    """证据条数多的在前，其次在线比大盘多涨得多的在前；算不出涨幅的排在同条数的最后。"""

    excess = entry.ccu_day_excess if entry.ccu_day_excess is not None else float("-inf")
    return (-len(entry.evidence), -excess, -entry.ccu, entry.name.casefold())


def _build_leader_status(
    view: _TrendView,
    place_id: int,
    candidate: _CandidateGame,
    *,
    judge_trend: bool = True,
) -> LeaderStatus | None:
    """在玩榜前列新游的势头：在线较上周同日的变化；不在在玩榜常规范围内时为 None。

    同一个星期几相比，周末效应自然抵消。上周同日有快照但没有这款游戏，说明它一周前还不在各榜前列，
    记为“新晋”；上周同日整天没有快照时不判断，不用其他日期代替。
    """

    rank = candidate.ranks_by_sheet.get(SPOTLIGHT_NEW_GAME_LEADER_SHEET_KEY)
    if rank is None or rank > SPOTLIGHT_MAX_CONSIDERED_RANK:
        return None
    ccu = view.ccu(place_id) or candidate.ccu
    # judge_trend 为 False（手动运行早于当天定时早报）时此刻与上周同日不是同一时刻，同样不判断。
    if not judge_trend or view.history is None or not view.has_snapshot_day(NEW_GAME_LEADER_WEEK_COMPARE_DAYS):
        return LeaderStatus(rank=rank, ccu=ccu, ccu_week_ago=None, week_change=None, state=None)
    ccu_week_ago = view.ccu(place_id, NEW_GAME_LEADER_WEEK_COMPARE_DAYS)
    if not ccu_week_ago:
        return LeaderStatus(rank=rank, ccu=ccu, ccu_week_ago=None, week_change=None, state="new")
    week_change = ccu / ccu_week_ago - 1
    if week_change >= NEW_GAME_LEADER_STATE_THRESHOLD:
        state: LeaderState = "up"
    elif week_change <= -NEW_GAME_LEADER_STATE_THRESHOLD:
        state = "down"
    else:
        state = "flat"
    return LeaderStatus(rank=rank, ccu=ccu, ccu_week_ago=ccu_week_ago, week_change=week_change, state=state)


def _build_earning_movement(
    place_id: int,
    candidate: _CandidateGame,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    oldest_earning_ranks: dict[int, int],
) -> EarningMovement | None:
    """计算收入榜位置与较上次、较一周前的变化；不在收入榜考察范围内时为 None。"""

    rank = candidate.ranks_by_sheet.get(TOP_EARNING_SHEET_KEY)
    if rank is None:
        return None
    previous_rank = previous_ranks_by_sheet.get(TOP_EARNING_SHEET_KEY, {}).get(place_id)
    week_change: int | None = None
    entered_this_week = False
    # 一周前的历史为空（刚上线或变量被清空）时无法判断走势，不能把所有游戏都当成新进榜。
    if oldest_earning_ranks:
        oldest_rank = oldest_earning_ranks.get(place_id)
        entered_this_week = oldest_rank is None
        week_change = (oldest_rank or SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK + 1) - rank
    return EarningMovement(
        rank=rank,
        change=previous_rank - rank if previous_rank is not None else None,
        week_change=week_change,
        entered_this_week=entered_this_week,
    )


def _judge_retention(metrics: GameTrendMetrics) -> RetentionVerdict | None:
    """留存结论：任一项明显偏低即留不住；单局时长与守住峰值都达标才算留得住；其余待观察。

    快照不足若干天时不判断。单局时长算不出（采样不足）或疑似挂机时不能判留得住，
    但守住峰值或好评率偏低仍判留不住。好评率可以用奖励引导，所以只在偏低时扣分、偏高不加分。
    """

    if metrics.recorded_days < LONG_TERM_MIN_RECORDED_DAYS:
        return None
    session = metrics.session_minutes
    session_note: Literal["missing", "afk"] | None = None
    if session is not None and session > LONG_TERM_SESSION_AFK_MINUTES:
        session, session_note = None, "afk"
    elif session is None:
        session_note = "missing"
    peak, like = metrics.peak_ratio, metrics.like_ratio
    if (
        (session is not None and session < RETENTION_BAD_SESSION_MINUTES)
        or (peak is not None and peak < RETENTION_BAD_PEAK_RATIO)
        or (like is not None and like < RETENTION_BAD_LIKE_RATIO)
    ):
        tier: RetentionTier = "bad"
    elif (
        session is not None
        and session >= RETENTION_GOOD_SESSION_MINUTES
        and peak is not None
        and peak >= RETENTION_GOOD_PEAK_RATIO
    ):
        tier = "good"
    else:
        tier = "watch"
    return RetentionVerdict(
        tier=tier,
        session_minutes=session,
        session_note=session_note,
        peak_ratio=peak,
        like_ratio=like,
    )
