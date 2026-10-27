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
)
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

SignalKind = Literal["new_game", "top_earning_entry", "new_entry", "rank_surge", "multi_sheet"]
# 只有这些“新鲜”信号能让游戏入选；多榜只做加分，否则常驻头部的老游戏会占满名单。
FRESH_SIGNAL_KINDS: frozenset[str] = frozenset({"new_game", "top_earning_entry", "new_entry", "rank_surge"})


@dataclass(frozen=True)
class SpotlightSignal:
    """一条入选理由及其得分。"""

    kind: SignalKind
    score: int
    reason: str


@dataclass(frozen=True)
class SpotlightEntry:
    """一个值得关注的游戏。"""

    place_id: int
    name: str
    genre: str
    ccu: int
    sheet_ranks: tuple[tuple[str, int], ...]
    signals: tuple[SpotlightSignal, ...]

    @property
    def score(self) -> int:
        """总分为各信号得分之和。"""

        return sum(signal.score for signal in self.signals)


@dataclass(frozen=True)
class MarketSpotlight:
    """早报中的值得关注项目；standout 为“今日最突出”，未达门槛时为 None。"""

    standout: SpotlightEntry | None
    entries: tuple[SpotlightEntry, ...]


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
) -> MarketSpotlight:
    """为各榜单前列游戏打分，选出“今日最突出”与其余值得关注项目。

    previous_ranks_by_sheet 为上一次运行的排名，用于判断排名飙升与收入榜新进前列；
    recent_place_ids_by_sheet 为最近若干次运行出现过的游戏，用于判断新上榜。
    """

    reference_date = resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return MarketSpotlight(standout=None, entries=())

    focus_place_ids_by_sheet = collect_top_trending_focus_place_ids_by_sheet(
        records_by_sheet,
        recent_place_ids_by_sheet,
    )
    scored: list[SpotlightEntry] = []
    for place_id, candidate in _collect_candidates(records_by_sheet).items():
        signals = _collect_signals(
            place_id,
            candidate,
            reference_date,
            previous_ranks_by_sheet,
            focus_place_ids_by_sheet,
        )
        if not any(signal.kind in FRESH_SIGNAL_KINDS for signal in signals):
            continue
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
            )
        )

    # 总分优先，同分比 CCU，再按名称保证结果稳定。
    scored.sort(key=lambda entry: (-entry.score, -entry.ccu, entry.name.casefold()))
    if scored and scored[0].score >= SPOTLIGHT_STANDOUT_MIN_SCORE:
        return MarketSpotlight(
            standout=scored[0],
            entries=tuple(scored[1:SPOTLIGHT_MAX_ENTRIES]),
        )
    return MarketSpotlight(standout=None, entries=tuple(scored[:SPOTLIGHT_MAX_ENTRIES]))


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


def _collect_candidates(records_by_sheet: dict[str, list[GameRecord]]) -> dict[int, _CandidateGame]:
    """把各榜单前列记录按游戏聚合，记录每个榜单的排名与最高 CCU。"""

    candidates: dict[int, _CandidateGame] = {}
    for sheet_key in SHEET_ORDER:
        for record in records_by_sheet.get(sheet_key, []):
            if record.place_id is None or record.rank > SPOTLIGHT_MAX_CONSIDERED_RANK:
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


def _collect_signals(
    place_id: int,
    candidate: _CandidateGame,
    reference_date: date,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    focus_place_ids_by_sheet: dict[str, set[int]],
) -> tuple[SpotlightSignal, ...]:
    """按规则逐项判定信号，信号顺序即理由的展示顺序。"""

    signals: list[SpotlightSignal] = []
    launch_date = resolve_launch_date(candidate.best_record)
    if launch_date is not None:
        age_days = (reference_date - launch_date).days
        if 0 <= age_days <= SPOTLIGHT_NEW_GAME_MAX_AGE_DAYS:
            signals.append(SpotlightSignal("new_game", SPOTLIGHT_NEW_GAME_SCORE, f"上线 {age_days} 天"))

    earning_rank = candidate.ranks_by_sheet.get(TOP_EARNING_SHEET_KEY)
    if earning_rank is not None and earning_rank <= SPOTLIGHT_TOP_EARNING_RANK_LIMIT:
        previous_earning_rank = previous_ranks_by_sheet.get(TOP_EARNING_SHEET_KEY, {}).get(place_id)
        if previous_earning_rank is None or previous_earning_rank > SPOTLIGHT_TOP_EARNING_RANK_LIMIT:
            signals.append(
                SpotlightSignal(
                    "top_earning_entry",
                    SPOTLIGHT_TOP_EARNING_SCORE,
                    f"新进{SHEET_LABELS[TOP_EARNING_SHEET_KEY]}前 {SPOTLIGHT_TOP_EARNING_RANK_LIMIT}",
                )
            )

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

    sheet_count = len(candidate.ranks_by_sheet)
    if sheet_count > 1:
        signals.append(
            SpotlightSignal(
                "multi_sheet",
                (sheet_count - 1) * SPOTLIGHT_MULTI_SHEET_SCORE_PER_EXTRA,
                f"同时在 {sheet_count} 个榜单",
            )
        )
    return tuple(signals)


def _build_rank_surge_signal(
    place_id: int,
    candidate: _CandidateGame,
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> SpotlightSignal | None:
    """取各榜单中较上次运行上升最多的一次，达到步长才算飙升。"""

    best_sheet_key = ""
    best_surge = 0
    for sheet_key in SHEET_ORDER:
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


def _most_common_genre(genres: Iterable[str]) -> tuple[str, int] | None:
    """返回出现最多的非空品类；达不到最少款数时返回 None。"""

    counter = Counter(genre for genre in genres if genre)
    if not counter:
        return None
    genre, count = counter.most_common(1)[0]
    if count < GENRE_MIN_COUNT:
        return None
    return genre, count
