"""行业趋势：值得关注项目打分与品类风向。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .daily_brief_rules import (
    GENRE_MIN_COUNT,
    GENRE_TRENDING_TOP_SIZE,
    LONG_TERM_BOARD_STREAK_DAYS,
    LONG_TERM_BOARD_STREAK_SCORE,
    LONG_TERM_EARNING_RANK_LIMIT,
    LONG_TERM_EARNING_SCORE,
    LONG_TERM_EARNING_WEEK_FALL_SCORE,
    LONG_TERM_EARNING_WEEK_FALL_STEP,
    LONG_TERM_EARNING_WEEK_RISE_SCORE,
    LONG_TERM_EARNING_WEEK_RISE_STEP,
    LONG_TERM_MAX_ENTRIES,
    LONG_TERM_MIN_RECORDED_DAYS,
    LONG_TERM_MIN_SCORE,
    LONG_TERM_PEAK_COLLAPSE_RATIO,
    LONG_TERM_PEAK_COLLAPSE_SCORE,
    LONG_TERM_PEAK_HOLD_RATIO,
    LONG_TERM_PEAK_HOLD_SCORE,
    LONG_TERM_RATING_HIGH,
    LONG_TERM_RATING_HIGH_SCORE,
    LONG_TERM_RATING_LOW,
    LONG_TERM_RATING_LOW_SCORE,
    LONG_TERM_RATING_TREND_DAYS,
    LONG_TERM_RATING_TREND_MIN_POINTS,
    LONG_TERM_RATING_TREND_SCORE,
    LONG_TERM_SESSION_AFK_MINUTES,
    LONG_TERM_SESSION_LONG_MINUTES,
    LONG_TERM_SESSION_LONG_SCORE,
    LONG_TERM_SESSION_SHORT_MINUTES,
    LONG_TERM_SESSION_SHORT_SCORE,
    LONG_TERM_TREND_COMPARE_DAYS,
    LONG_TERM_TREND_FALL_TIERS,
    LONG_TERM_TREND_RISE_TIERS,
    SPOTLIGHT_EARNING_DEEP_RANK_MAX_AGE_DAYS,
    SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK,
    SPOTLIGHT_EARNING_SURGE_BONUS_PER_STEP,
    SPOTLIGHT_EARNING_SURGE_MAX_BONUS,
    SPOTLIGHT_EARNING_SURGE_MIN_STEP,
    SPOTLIGHT_EARNING_SURGE_SCORE,
    SPOTLIGHT_EARNING_TOP100_RANK_LIMIT,
    SPOTLIGHT_EARNING_TOP100_SCORE,
    SPOTLIGHT_EARNING_WEEKLY_CLIMB_MIN_STEP,
    SPOTLIGHT_EARNING_WEEKLY_CLIMB_SCORE,
    SPOTLIGHT_MAX_CONSIDERED_RANK,
    SPOTLIGHT_MAX_ENTRIES,
    SPOTLIGHT_MULTI_SHEET_SCORE_PER_EXTRA,
    SPOTLIGHT_NEW_ENTRY_SCORE,
    SPOTLIGHT_NEW_GAME_MAX_AGE_DAYS,
    SPOTLIGHT_NEW_GAME_SCORE,
    SPOTLIGHT_RANK_SURGE_BONUS_PER_STEP,
    SPOTLIGHT_RANK_SURGE_MAX_BONUS,
    SPOTLIGHT_RANK_SURGE_MIN_STEP,
    SPOTLIGHT_RANK_SURGE_SCORE,
    SPOTLIGHT_STANDOUT_MIN_SCORE,
    SPOTLIGHT_TOP_EARNING_RANK_LIMIT,
    SPOTLIGHT_TOP_EARNING_SCORE,
    TREND_HISTORY_KEEP_DAYS,
)
from .game_trend_history import GameDailySnapshot, GameTrendHistory, GameTrendMetrics, build_game_trend_metrics
from .models import GameRecord
from .top_trending_briefing import (
    SHEET_LABELS,
    SHEET_ORDER,
    build_briefing_display_name,
    collect_top_trending_focus_place_ids_by_sheet,
    resolve_launch_date,
    resolve_reference_date,
)


# 榜单键：收入榜、热门榜在打分与品类统计中有专门含义。
TOP_EARNING_SHEET_KEY = "top_earning"
TOP_TRENDING_SHEET_KEY = "top_trending_v4"

SignalKind = Literal[
    "new_game",
    "top_earning_entry",
    "new_entry",
    "rank_surge",
    "multi_sheet",
    "ccu_trend",
    "peak_hold",
    "board_streak",
    "session",
    "rating",
    "rating_trend",
    "earning",
    "earning_surge",
    "earning_top100_entry",
    "earning_weekly_climb",
]
# 收入榜上升信号：收入榜 100 名以后的游戏只有具备其中之一才入选。
EARNING_RISE_SIGNAL_KINDS: frozenset[str] = frozenset({"earning_surge", "earning_top100_entry", "earning_weekly_climb"})
# 只有这些“新鲜”信号能让游戏入选；多榜只做加分，否则常驻头部的老游戏会占满名单。
FRESH_SIGNAL_KINDS: frozenset[str] = (
    frozenset({"new_game", "top_earning_entry", "new_entry", "rank_surge"}) | EARNING_RISE_SIGNAL_KINDS
)


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
class SpotlightSignal:
    """一条入选理由及其得分；长线信号得分可以为 0 或负数，理由照常展示。"""

    kind: SignalKind
    score: int
    reason: str


@dataclass(frozen=True)
class SpotlightEntry:
    """一个值得关注的游戏。

    signals 衡量“爆发”，决定今日最突出与值得关注的排序；long_term_signals 衡量能否长线，
    历史快照不足时为空。
    """

    place_id: int
    name: str
    genre: str
    ccu: int
    sheet_ranks: tuple[tuple[str, int], ...]
    signals: tuple[SpotlightSignal, ...]
    long_term_signals: tuple[SpotlightSignal, ...] = ()
    earning: EarningMovement | None = None

    @property
    def score(self) -> int:
        """爆发分为各信号得分之和。"""

        return sum(signal.score for signal in self.signals)

    @property
    def long_term_score(self) -> int:
        """长线分为各长线信号得分之和。"""

        return sum(signal.score for signal in self.long_term_signals)


@dataclass(frozen=True)
class MarketSpotlight:
    """早报中的值得关注项目。

    standout 为“今日最突出（爆发）”，未达门槛时为 None；long_term 为“长线潜力”；
    entries 为其余值得关注项目，三者互不重复。long_term_recorded_days 为候选游戏中最多的快照天数，
    用于提示长线指标还在积累。
    """

    standout: SpotlightEntry | None
    entries: tuple[SpotlightEntry, ...]
    long_term: tuple[SpotlightEntry, ...] = ()
    long_term_recorded_days: int = 0


@dataclass(frozen=True)
class _CandidateGame:
    """聚合同一游戏在各榜单中的表现，供打分使用。"""

    best_record: GameRecord
    ranks_by_sheet: dict[str, int]
    ccu: int


def build_market_spotlight(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    recent_place_ids_by_sheet: dict[str, set[int]],
    trend_snapshots: dict[int, GameDailySnapshot] | None = None,
    trend_history: GameTrendHistory | None = None,
    oldest_ranks_by_sheet: dict[str, dict[int, int]] | None = None,
) -> MarketSpotlight:
    """为各榜单前列游戏打分，选出“今日最突出（爆发）”“长线潜力”与其余值得关注项目。

    previous_ranks_by_sheet 为上一次运行的排名，用于判断排名飙升与收入榜新进前列；
    recent_place_ids_by_sheet 为最近若干次运行出现过的游戏，用于判断新上榜；
    trend_snapshots 为当天的游戏快照，trend_history 为此前的每日快照，两者用于计算长线指标；
    oldest_ranks_by_sheet 为已保存历史中最早一次运行的排名，用于计算收入榜一周走势。
    """

    reference_date = resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return MarketSpotlight(standout=None, entries=())

    focus_place_ids_by_sheet = collect_top_trending_focus_place_ids_by_sheet(
        records_by_sheet,
        recent_place_ids_by_sheet,
    )
    scored: list[SpotlightEntry] = []
    long_term_recorded_days = 0
    for place_id, candidate in _collect_candidates(records_by_sheet, reference_date).items():
        earning = _build_earning_movement(
            place_id,
            candidate,
            previous_ranks_by_sheet,
            (oldest_ranks_by_sheet or {}).get(TOP_EARNING_SHEET_KEY, {}),
        )
        signals = _collect_signals(
            place_id,
            candidate,
            reference_date,
            previous_ranks_by_sheet,
            focus_place_ids_by_sheet,
            earning,
        )
        if not any(signal.kind in FRESH_SIGNAL_KINDS for signal in signals):
            continue
        # 只在收入榜 100 名以后出现的游戏，必须正在爬收入榜才值得关注，否则新上榜的长尾会刷屏。
        if not _is_in_considered_range(candidate) and not any(
            signal.kind in EARNING_RISE_SIGNAL_KINDS for signal in signals
        ):
            continue
        long_term_signals: tuple[SpotlightSignal, ...] = ()
        snapshot = (trend_snapshots or {}).get(place_id)
        if snapshot is not None:
            metrics = build_game_trend_metrics(snapshot, (trend_history or {}).get(place_id, []))
            long_term_recorded_days = max(long_term_recorded_days, metrics.recorded_days)
            if metrics.recorded_days >= LONG_TERM_MIN_RECORDED_DAYS:
                long_term_signals = _collect_long_term_signals(metrics, earning)
        scored.append(
            SpotlightEntry(
                place_id=place_id,
                name=build_briefing_display_name(candidate.best_record),
                genre=candidate.best_record.genre.strip(),
                ccu=candidate.ccu,
                sheet_ranks=tuple(
                    (SHEET_LABELS[sheet_key], candidate.ranks_by_sheet[sheet_key])
                    for sheet_key in SHEET_ORDER
                    if sheet_key in candidate.ranks_by_sheet
                ),
                signals=signals,
                long_term_signals=long_term_signals,
                earning=earning,
            )
        )

    # 总分优先，同分时收入榜排名靠前的优先，再比 CCU，最后按名称保证结果稳定。
    scored.sort(key=lambda entry: (-entry.score, _earning_sort_rank(entry), -entry.ccu, entry.name.casefold()))
    standout = scored[0] if scored and scored[0].score >= SPOTLIGHT_STANDOUT_MIN_SCORE else None
    # 长线潜力不重复展示今日最突出；长线分达到门槛才入选，没有就不硬凑。
    long_term = sorted(
        (
            entry
            for entry in scored
            if entry is not standout and entry.long_term_signals and entry.long_term_score >= LONG_TERM_MIN_SCORE
        ),
        key=lambda entry: (-entry.long_term_score, _earning_sort_rank(entry), -entry.ccu, entry.name.casefold()),
    )[:LONG_TERM_MAX_ENTRIES]
    shown_place_ids = {entry.place_id for entry in long_term}
    if standout is not None:
        shown_place_ids.add(standout.place_id)
    remaining_slots = SPOTLIGHT_MAX_ENTRIES - len(shown_place_ids)
    return MarketSpotlight(
        standout=standout,
        entries=tuple(entry for entry in scored if entry.place_id not in shown_place_ids)[:remaining_slots],
        long_term=tuple(long_term),
        long_term_recorded_days=long_term_recorded_days,
    )


def build_genre_wind_lines(
    records_by_sheet: dict[str, list[GameRecord]],
    recent_place_ids_by_sheet: dict[str, set[int]],
) -> tuple[str, ...]:
    """生成品类风向描述：新上榜游戏的集中品类、热门榜前列的主流品类。"""

    lines: list[str] = []
    focus_place_ids = {
        place_id
        for place_ids in collect_top_trending_focus_place_ids_by_sheet(
            records_by_sheet,
            recent_place_ids_by_sheet,
        ).values()
        for place_id in place_ids
    }
    new_entry_genres = {
        record.place_id: record.genre.strip()
        for sheet_key in SHEET_ORDER
        for record in records_by_sheet.get(sheet_key, [])
        if record.place_id in focus_place_ids and record.rank <= SPOTLIGHT_MAX_CONSIDERED_RANK
    }
    top_new_genre = _most_common_genre(new_entry_genres.values())
    if top_new_genre is not None:
        genre, count = top_new_genre
        lines.append(f"今日新上榜 {len(new_entry_genres)} 款中 {count} 款是 {genre}")

    trending_genres = [
        record.genre.strip()
        for record in records_by_sheet.get(TOP_TRENDING_SHEET_KEY, [])
        if record.rank <= GENRE_TRENDING_TOP_SIZE
    ]
    top_trending_genre = _most_common_genre(trending_genres)
    if top_trending_genre is not None:
        genre, count = top_trending_genre
        lines.append(
            f"{SHEET_LABELS[TOP_TRENDING_SHEET_KEY]}前 {GENRE_TRENDING_TOP_SIZE} 名中 {genre} 占 {count} 款"
        )
    return tuple(lines)


def _collect_candidates(
    records_by_sheet: dict[str, list[GameRecord]],
    reference_date: date,
) -> dict[int, _CandidateGame]:
    """把各榜单前列记录按游戏聚合，记录每个榜单的排名与最高 CCU。

    收入榜对较新的游戏放宽到更靠后的名次，用来发现正在爬收入榜的新游。
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
    launch_date = resolve_launch_date(record)
    if launch_date is None or (reference_date - launch_date).days > SPOTLIGHT_EARNING_DEEP_RANK_MAX_AGE_DAYS:
        return SPOTLIGHT_MAX_CONSIDERED_RANK
    return SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK


def _is_in_considered_range(candidate: _CandidateGame) -> bool:
    """是否至少在一个榜单的常规考察范围（前 N 名）内。"""

    return any(rank <= SPOTLIGHT_MAX_CONSIDERED_RANK for rank in candidate.ranks_by_sheet.values())


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


def _collect_signals(
    place_id: int,
    candidate: _CandidateGame,
    reference_date: date,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    focus_place_ids_by_sheet: dict[str, set[int]],
    earning: EarningMovement | None,
) -> tuple[SpotlightSignal, ...]:
    """按规则逐项判定信号，信号顺序即理由的展示顺序；收入榜信号排在前面，便于一眼看到。"""

    signals: list[SpotlightSignal] = []
    launch_date = resolve_launch_date(candidate.best_record)
    if launch_date is not None:
        age_days = (reference_date - launch_date).days
        if 0 <= age_days <= SPOTLIGHT_NEW_GAME_MAX_AGE_DAYS:
            signals.append(SpotlightSignal("new_game", SPOTLIGHT_NEW_GAME_SCORE, f"上线 {age_days} 天"))

    signals.extend(_build_earning_signals(earning, bool(previous_ranks_by_sheet.get(TOP_EARNING_SHEET_KEY))))

    new_entry_labels = [
        SHEET_LABELS[sheet_key]
        for sheet_key in SHEET_ORDER
        if sheet_key in candidate.ranks_by_sheet
        and place_id in focus_place_ids_by_sheet.get(sheet_key, set())
    ]
    if new_entry_labels:
        signals.append(
            SpotlightSignal("new_entry", SPOTLIGHT_NEW_ENTRY_SCORE, f"新上{'、'.join(new_entry_labels)}")
        )

    surge_signal = _build_rank_surge_signal(place_id, candidate, previous_ranks_by_sheet)
    if surge_signal is not None:
        signals.append(surge_signal)

    # 多榜只统计常规考察范围内的排名，收入榜靠后的名次不算“同时在榜”。
    sheet_count = sum(1 for rank in candidate.ranks_by_sheet.values() if rank <= SPOTLIGHT_MAX_CONSIDERED_RANK)
    if sheet_count > 1:
        signals.append(
            SpotlightSignal(
                "multi_sheet",
                (sheet_count - 1) * SPOTLIGHT_MULTI_SHEET_SCORE_PER_EXTRA,
                f"同时在 {sheet_count} 个榜单",
            )
        )
    return tuple(signals)


def _build_earning_signals(
    earning: EarningMovement | None,
    has_previous_earning_ranks: bool,
) -> list[SpotlightSignal]:
    """收入榜单独计分：新进前 20 或冲进前 100、较上次飙升、一周爬升。

    上次运行没有收入榜历史时不判断“冲进前 100”，避免首次运行把所有游戏都当成新进榜。
    """

    if earning is None:
        return []
    label = SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    previous_rank = earning.rank + earning.change if earning.change is not None else None
    signals: list[SpotlightSignal] = []
    if earning.rank <= SPOTLIGHT_TOP_EARNING_RANK_LIMIT and (
        previous_rank is None or previous_rank > SPOTLIGHT_TOP_EARNING_RANK_LIMIT
    ):
        signals.append(
            SpotlightSignal("top_earning_entry", SPOTLIGHT_TOP_EARNING_SCORE, f"新进{label}前 {SPOTLIGHT_TOP_EARNING_RANK_LIMIT}")
        )
    elif (
        has_previous_earning_ranks
        and earning.rank <= SPOTLIGHT_EARNING_TOP100_RANK_LIMIT
        and (previous_rank is None or previous_rank > SPOTLIGHT_EARNING_TOP100_RANK_LIMIT)
    ):
        signals.append(
            SpotlightSignal(
                "earning_top100_entry",
                SPOTLIGHT_EARNING_TOP100_SCORE,
                f"冲进{label}前 {SPOTLIGHT_EARNING_TOP100_RANK_LIMIT}",
            )
        )

    if earning.change is not None and earning.change >= SPOTLIGHT_EARNING_SURGE_MIN_STEP:
        # 基础分之外，每多上升一个步长再加分，加分有上限。
        extra_steps = (earning.change - SPOTLIGHT_EARNING_SURGE_MIN_STEP) // SPOTLIGHT_EARNING_SURGE_MIN_STEP
        bonus = min(SPOTLIGHT_EARNING_SURGE_MAX_BONUS, extra_steps * SPOTLIGHT_EARNING_SURGE_BONUS_PER_STEP)
        signals.append(
            SpotlightSignal("earning_surge", SPOTLIGHT_EARNING_SURGE_SCORE + bonus, f"{label}较上次 ↑{earning.change}")
        )

    if earning.week_change is not None and earning.week_change >= SPOTLIGHT_EARNING_WEEKLY_CLIMB_MIN_STEP:
        signals.append(
            SpotlightSignal("earning_weekly_climb", SPOTLIGHT_EARNING_WEEKLY_CLIMB_SCORE, _format_earning_week(earning))
        )
    return signals


def _format_earning_week(earning: EarningMovement) -> str:
    """一周走势的文字；一周前不在榜时写明从榜外升上来，而不是给出按末位推算的名次差。"""

    label = SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    if earning.entered_this_week:
        return f"{label}一周内从 {SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK} 名外升至 #{earning.rank}"
    assert earning.week_change is not None
    arrow = "↑" if earning.week_change >= 0 else "↓"
    return f"{label} #{earning.rank}（一周 {arrow}{abs(earning.week_change)}）"


def _earning_sort_rank(entry: SpotlightEntry) -> int:
    """排序用的收入榜名次；不在收入榜的排在最后。"""

    return entry.earning.rank if entry.earning is not None else SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK + 1


def _build_rank_surge_signal(
    place_id: int,
    candidate: _CandidateGame,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> SpotlightSignal | None:
    """取收入榜以外各榜单中较上次运行上升最多的一次，达到步长才算飙升；收入榜飙升单独计分。"""

    best_sheet_key = ""
    best_surge = 0
    for sheet_key in SHEET_ORDER:
        if sheet_key == TOP_EARNING_SHEET_KEY:
            continue
        current_rank = candidate.ranks_by_sheet.get(sheet_key)
        previous_rank = previous_ranks_by_sheet.get(sheet_key, {}).get(place_id)
        if current_rank is None or previous_rank is None:
            continue
        surge = previous_rank - current_rank
        if surge > best_surge:
            best_sheet_key, best_surge = sheet_key, surge
    if best_surge < SPOTLIGHT_RANK_SURGE_MIN_STEP:
        return None

    # 基础分之外，每多上升一个步长再加分，加分有上限，防止单一信号压过其他信号。
    extra_steps = (best_surge - SPOTLIGHT_RANK_SURGE_MIN_STEP) // SPOTLIGHT_RANK_SURGE_MIN_STEP
    bonus = min(SPOTLIGHT_RANK_SURGE_MAX_BONUS, extra_steps * SPOTLIGHT_RANK_SURGE_BONUS_PER_STEP)
    return SpotlightSignal(
        "rank_surge",
        SPOTLIGHT_RANK_SURGE_SCORE + bonus,
        f"{SHEET_LABELS[best_sheet_key]}较上次 ↑{best_surge}",
    )


def _collect_long_term_signals(
    metrics: GameTrendMetrics,
    earning: EarningMovement | None,
) -> tuple[SpotlightSignal, ...]:
    """按长线规则逐项打分；能算出的指标都展示理由，得分为 0 的也保留，方便判断依据。"""

    signals: list[SpotlightSignal] = []
    if metrics.ccu_change_ratio is not None:
        signals.append(
            SpotlightSignal(
                "ccu_trend",
                _ccu_trend_score(metrics.ccu_change_ratio),
                f"在线较前 {LONG_TERM_TREND_COMPARE_DAYS} 日 {_format_percent_change(metrics.ccu_change_ratio)}",
            )
        )

    if metrics.peak_ratio is not None:
        if metrics.peak_ratio >= LONG_TERM_PEAK_HOLD_RATIO:
            peak_score = LONG_TERM_PEAK_HOLD_SCORE
        elif metrics.peak_ratio < LONG_TERM_PEAK_COLLAPSE_RATIO:
            peak_score = LONG_TERM_PEAK_COLLAPSE_SCORE
        else:
            peak_score = 0
        peak_reason = (
            f"处于 {TREND_HISTORY_KEEP_DAYS} 日峰值"
            if metrics.peak_ratio >= 1
            else f"较 {TREND_HISTORY_KEEP_DAYS} 日峰值 {_format_percent_change(metrics.peak_ratio - 1)}"
        )
        signals.append(SpotlightSignal("peak_hold", peak_score, peak_reason))

    if metrics.board_streak_days >= LONG_TERM_BOARD_STREAK_DAYS:
        signals.append(
            SpotlightSignal("board_streak", LONG_TERM_BOARD_STREAK_SCORE, f"连续在榜 {metrics.board_streak_days} 天")
        )

    if metrics.session_minutes is not None:
        if metrics.session_minutes > LONG_TERM_SESSION_AFK_MINUTES:
            signals.append(SpotlightSignal("session", 0, "疑似挂机，时长不计分"))
        else:
            if metrics.session_minutes >= LONG_TERM_SESSION_LONG_MINUTES:
                session_score = LONG_TERM_SESSION_LONG_SCORE
            elif metrics.session_minutes < LONG_TERM_SESSION_SHORT_MINUTES:
                session_score = LONG_TERM_SESSION_SHORT_SCORE
            else:
                session_score = 0
            signals.append(
                SpotlightSignal("session", session_score, f"估算时长 {metrics.session_minutes:.0f} 分钟")
            )

    if metrics.like_ratio is not None:
        if metrics.like_ratio >= LONG_TERM_RATING_HIGH:
            rating_score = LONG_TERM_RATING_HIGH_SCORE
        elif metrics.like_ratio < LONG_TERM_RATING_LOW:
            rating_score = LONG_TERM_RATING_LOW_SCORE
        else:
            rating_score = 0
        label = "新增好评" if metrics.like_ratio_is_recent else "好评"
        signals.append(SpotlightSignal("rating", rating_score, f"{label} {metrics.like_ratio:.0%}"))

    if metrics.like_ratio_change is not None and metrics.like_ratio_change >= LONG_TERM_RATING_TREND_MIN_POINTS:
        signals.append(
            SpotlightSignal(
                "rating_trend",
                LONG_TERM_RATING_TREND_SCORE,
                f"好评率较 {LONG_TERM_RATING_TREND_DAYS} 日前 +{metrics.like_ratio_change * 100:.1f} 个点",
            )
        )

    earning_signal = _build_long_term_earning_signal(earning)
    if earning_signal is not None:
        signals.append(earning_signal)
    return tuple(signals)


def _build_long_term_earning_signal(earning: EarningMovement | None) -> SpotlightSignal | None:
    """变现看收入榜一周走势：明显上升加分、明显下滑扣分（付费在消退），平稳但在前列时加基础分。"""

    if earning is None:
        return None
    week_change = earning.week_change
    if week_change is not None and week_change >= LONG_TERM_EARNING_WEEK_RISE_STEP:
        return SpotlightSignal("earning", LONG_TERM_EARNING_WEEK_RISE_SCORE, _format_earning_week(earning))
    if week_change is not None and week_change <= -LONG_TERM_EARNING_WEEK_FALL_STEP:
        return SpotlightSignal("earning", LONG_TERM_EARNING_WEEK_FALL_SCORE, _format_earning_week(earning))
    if earning.rank <= LONG_TERM_EARNING_RANK_LIMIT:
        return SpotlightSignal("earning", LONG_TERM_EARNING_SCORE, f"{SHEET_LABELS[TOP_EARNING_SHEET_KEY]} #{earning.rank}")
    return None


def _ccu_trend_score(change_ratio: float) -> int:
    """按分档匹配在线涨跌得分；涨跌都没达到最低一档时为平稳，不加不减。"""

    for threshold, score in LONG_TERM_TREND_RISE_TIERS:
        if change_ratio >= threshold:
            return score
    for threshold, score in LONG_TERM_TREND_FALL_TIERS:
        if change_ratio <= threshold:
            return score
    return 0


def _format_percent_change(ratio: float) -> str:
    return f"{ratio * 100:+.0f}%"


def _most_common_genre(genres: Iterable[str]) -> tuple[str, int] | None:
    """返回出现最多的非空品类；达不到最少款数时返回 None。"""

    counter = Counter(genre for genre in genres if genre)
    if not counter:
        return None
    genre, count = counter.most_common(1)[0]
    if count < GENRE_MIN_COUNT:
        return None
    return genre, count
