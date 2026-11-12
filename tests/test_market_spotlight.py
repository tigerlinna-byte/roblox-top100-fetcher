from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.game_trend_history import GameDailySnapshot, GameTrendHistory
from app.market_pulse import MarketCcuSnapshot, MarketPulse
from app.market_spotlight import (
    MarketSpotlight,
    build_genre_wind_lines,
    build_market_spotlight,
    build_new_game_genre_counts,
)
from app.models import GameRecord


TODAY = date(2026, 10, 27)
FETCHED_AT = "2026-10-27T01:00:00Z"
# 创建 17 天的新游与创建一年多的老游戏。
YOUNG = "2026-10-10T00:00:00Z"
OLD = "2025-01-01T00:00:00Z"
# 只用来让某一天“有快照”的陪衬游戏，不出现在当天榜单里。
FILLER_PLACE_ID = 999


def _day(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _snapshot(
    day: str,
    ccu: int,
    visits: int = 0,
    up: int = 0,
    down: int = 0,
    average_ccu: int | None = None,
) -> GameDailySnapshot:
    return GameDailySnapshot(
        snapshot_date=day,
        ccu=ccu,
        visits=visits,
        up_votes=up,
        down_votes=down,
        average_ccu=average_ccu,
        peak_ccu=None if average_ccu is None else average_ccu * 2,
        ccu_sample_count=0 if average_ccu is None else 4,
    )


def _record(
    rank: int,
    place_id: int,
    *,
    created_at: str = YOUNG,
    playing: int = 5000,
    genre: str = "Simulation",
) -> GameRecord:
    return GameRecord(
        rank=rank,
        place_id=place_id,
        universe_id=place_id + 1000,
        name=f"Game {place_id}",
        genre=genre,
        playing=playing,
        fetched_at=FETCHED_AT,
        created_at=created_at,
    )


def _history(ccu_by_place_and_days_ago: dict[int, dict[int, int]]) -> GameTrendHistory:
    """按“几天前 -> CCU”构造快照历史；陪衬游戏保证昨天有快照。"""

    history: GameTrendHistory = {FILLER_PLACE_ID: [_snapshot(_day(1), 1)]}
    for place_id, ccu_by_days_ago in ccu_by_place_and_days_ago.items():
        history[place_id] = [_snapshot(_day(days_ago), ccu) for days_ago, ccu in sorted(ccu_by_days_ago.items())]
    return history


def _snapshots(records_by_sheet: dict[str, list[GameRecord]]) -> dict[int, GameDailySnapshot]:
    return {
        record.place_id: _snapshot(_day(0), record.playing)
        for records in records_by_sheet.values()
        for record in records
    }


def _flat_market(*days_ago: int) -> dict[str, int]:
    return {_day(offset): 1_000_000 for offset in (0, *days_ago)}


def _build(
    records_by_sheet: dict[str, list[GameRecord]],
    history: GameTrendHistory | None,
    *,
    previous_ranks: dict[str, dict[int, int]] | None = None,
    recent_place_ids: dict[str, set[int]] | None = None,
    oldest_ranks: dict[str, dict[int, int]] | None = None,
    market: dict[str, int] | None = None,
    hit_history: dict | None = None,
    snapshots: dict[int, GameDailySnapshot] | None = None,
    scheduled: bool = True,
) -> MarketSpotlight:
    """scheduled 为 True 时模拟定时早报：当天快照已先存进历史；为 False 时模拟早于当天定时早报的手动运行。"""

    today_snapshots = snapshots if snapshots is not None else _snapshots(records_by_sheet)
    if scheduled and history is not None and history:
        history = {
            place_id: [*history.get(place_id, []), *([today_snapshots[place_id]] if place_id in today_snapshots else [])]
            for place_id in set(history) | set(today_snapshots)
        }
    return build_market_spotlight(
        records_by_sheet,
        previous_ranks or {},
        recent_place_ids or {},
        today_snapshots,
        history,
        oldest_ranks,
        market_ccu_by_date=market if market is not None else _flat_market(1, 3),
        hit_history=hit_history,
        brief_date=TODAY,
    )


def _ids(entries: tuple) -> list[int]:
    return [entry.place_id for entry in entries]


def _evidence(entry) -> list[str]:
    return [item.text for item in entry.evidence]


class NewFaceTests(unittest.TestCase):
    def test_games_without_recent_snapshots_are_new_faces_sorted_by_ccu(self) -> None:
        records = {
            "up_and_coming_v4": [
                _record(15, 1, playing=4359),
                _record(33, 2, playing=11850),
                _record(40, 3, playing=7000),
            ]
        }

        spotlight = _build(records, _history({3: {1: 6000}}))

        self.assertEqual(2, spotlight.new_face_standout.place_id)
        self.assertEqual([2, 1], _ids(spotlight.all_new_faces))
        self.assertEqual(1, spotlight.new_face_standout.days_on_board)
        self.assertEqual(17, spotlight.new_face_standout.age_days)
        self.assertEqual((), spotlight.new_face_standout.evidence)
        self.assertEqual(1, spotlight.new_face_lookback_days)

    def test_lookback_covers_fourteen_days_before_today(self) -> None:
        records = {"up_and_coming_v4": [_record(1, 1), _record(2, 2)]}

        spotlight = _build(records, _history({1: {14: 4000}, 2: {15: 4000}}))

        # 14 天前上过榜的不算新面孔，15 天前的已经超出回看范围。
        self.assertEqual([2], _ids(spotlight.all_new_faces))

    def test_detail_list_holds_six_and_the_rest_overflow(self) -> None:
        records = {"up_and_coming_v4": [_record(rank, rank, playing=20000 - rank * 1000) for rank in range(1, 9)]}

        spotlight = _build(records, _history({}))

        self.assertEqual(1, spotlight.new_face_standout.place_id)
        self.assertEqual([2, 3, 4, 5, 6], _ids(spotlight.new_faces))
        self.assertEqual([7, 8], _ids(spotlight.new_face_overflow))

    def test_new_game_first_seen_deep_in_earning_board_is_a_new_face(self) -> None:
        records = {
            "top_earning": [
                _record(223, 31, playing=3800),
                # 老游戏在收入榜 100 名以后不在考察范围内。
                _record(150, 32, created_at=OLD, playing=9000),
            ]
        }

        spotlight = _build(records, _history({}))

        self.assertEqual([31], _ids(spotlight.all_new_faces))

    def test_small_or_undated_games_are_excluded(self) -> None:
        records = {
            "up_and_coming_v4": [
                _record(1, 1, playing=2999),
                _record(2, 2, created_at=""),
                _record(3, 3, created_at=OLD),
            ]
        }

        spotlight = _build(records, _history({}))

        self.assertEqual((), spotlight.all_new_faces)
        self.assertEqual((), spotlight.all_growth)


class GrowthTests(unittest.TestCase):
    def test_ccu_evidence_deducts_market_change(self) -> None:
        records = {"top_trending_v4": [_record(10, 1, playing=9000)]}
        history = _history({1: {1: 5000}})
        recent = {"top_trending_v4": {1}}

        flat = _build(records, history, recent_place_ids=recent, market=_flat_market(1, 3))
        # 游戏涨 80%，但大盘同期涨了 50%，只比大盘多涨 20%，不算增长。
        weekend = _build(
            records,
            history,
            recent_place_ids=recent,
            market={_day(0): 1_500_000, _day(1): 1_000_000, _day(3): 1_000_000},
        )

        self.assertEqual(["在线比大盘多涨 80%（较昨天）"], _evidence(flat.growth_standout))
        self.assertAlmostEqual(0.8, flat.growth_standout.ccu_day_excess)
        self.assertEqual(2, flat.growth_standout.days_on_board)
        self.assertIsNone(weekend.growth_standout)

    def test_ccu_evidence_falls_back_to_three_day_window(self) -> None:
        records = {"top_trending_v4": [_record(10, 1, playing=9000)]}
        history = _history({1: {1: 8000, 3: 4000}})
        history[FILLER_PLACE_ID].append(_snapshot(_day(3), 1))

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": {1}})

        self.assertEqual(["在线比大盘多涨 125%（较 3 天前）"], _evidence(spotlight.growth_standout))
        self.assertEqual((), spotlight.problems)

    def test_entries_with_more_evidence_rank_first(self) -> None:
        records = {
            "top_trending_v4": [_record(10, 1, playing=6000), _record(20, 2, playing=40000)],
            "top_earning": [_record(120, 1, playing=6000)],
        }
        history = _history({1: {1: 6000}, 2: {1: 10000}})

        spotlight = _build(
            records,
            history,
            previous_ranks={"top_earning": {1: 145}},
            recent_place_ids={"top_trending_v4": {2}, "top_earning": {1}},
        )

        self.assertEqual([1, 2], _ids(spotlight.all_growth))
        self.assertEqual(["新进热门榜", "收入榜 ↑25"], _evidence(spotlight.growth_standout))
        self.assertEqual(["ccu"], [item.kind for item in spotlight.growth[0].evidence])
        self.assertEqual((120, 25), (spotlight.growth_standout.earning.rank, spotlight.growth_standout.earning.change))

    def test_earning_evidence_covers_entry_rise_and_top100(self) -> None:
        records = {
            "top_earning": [
                _record(95, 1),
                _record(150, 2),
                _record(200, 3),
                _record(250, 4),
            ]
        }
        history = _history({place_id: {1: 5000} for place_id in (1, 2, 3, 4)})

        spotlight = _build(
            records,
            history,
            previous_ranks={"top_earning": {1: 104, 2: 171, 4: 262}},
            recent_place_ids={"top_earning": {1, 2, 4}},
        )

        evidence = {entry.place_id: _evidence(entry) for entry in spotlight.all_growth}
        # 4 只上升 12 名，不到步长，也没有冲进前 100。
        self.assertEqual({1: ["冲进收入榜前 100"], 2: ["收入榜 ↑21"], 3: ["新进收入榜"]}, evidence)

    def test_boards_without_history_do_not_mark_every_game_as_entering(self) -> None:
        records = {
            "top_trending_v4": [_record(10, 1)],
            "top_playing_now": [_record(80, 1)],
            "top_earning": [_record(80, 1)],
        }

        spotlight = _build(records, _history({1: {1: 5000}}))

        self.assertEqual((), spotlight.all_growth)

    def test_growth_streak_counts_consecutive_days_from_hit_history(self) -> None:
        records = {"top_trending_v4": [_record(10, 1, playing=9000)]}
        hit_history = {
            _day(1): {"new_face": frozenset(), "growth": frozenset({1})},
            _day(2): {"new_face": frozenset(), "growth": frozenset({1})},
            _day(4): {"new_face": frozenset(), "growth": frozenset({1})},
        }

        spotlight = _build(
            records,
            _history({1: {1: 5000}}),
            recent_place_ids={"top_trending_v4": {1}},
            hit_history=hit_history,
        )

        # 昨天、前天连续命中，加上今天是第 3 天；4 天前那次中间断过，不算。
        self.assertEqual(3, spotlight.growth_standout.growth_streak_days)

    def test_detail_list_holds_eight_and_the_rest_overflow(self) -> None:
        records = {"top_trending_v4": [_record(rank, rank, playing=5000 + rank) for rank in range(1, 11)]}
        history = _history({rank: {1: 1000 + rank * 100} for rank in range(1, 11)})

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": set(range(1, 11))})

        # 昨天 CCU 越低的今天涨幅越大，排在前面。
        self.assertEqual(1, spotlight.growth_standout.place_id)
        self.assertEqual([2, 3, 4, 5, 6, 7, 8], _ids(spotlight.growth))
        self.assertEqual([9, 10], _ids(spotlight.growth_overflow))

    def test_old_games_are_ignored_even_when_climbing_earning_board(self) -> None:
        records = {"top_earning": [_record(31, 1, created_at=OLD, playing=31000)]}

        spotlight = _build(
            records,
            _history({}),
            previous_ranks={"top_earning": {1: 212}},
            recent_place_ids={"top_earning": {1}},
        )

        self.assertEqual((), spotlight.all_growth)
        self.assertEqual((), spotlight.all_new_faces)


class MissingHistoryTests(unittest.TestCase):
    def test_unreadable_history_skips_new_faces_and_reports_problem(self) -> None:
        records = {"top_trending_v4": [_record(10, 1)]}

        spotlight = _build(records, None, recent_place_ids={"top_trending_v4": {2}})

        self.assertEqual(0, spotlight.new_face_lookback_days)
        self.assertEqual((), spotlight.all_new_faces)
        # 不依赖快照的晋榜证据照常判断。
        self.assertEqual(["新进热门榜"], _evidence(spotlight.growth_standout))
        self.assertIsNone(spotlight.growth_standout.days_on_board)
        self.assertEqual(("游戏每日快照读取失败，今天不判断新面孔、在线涨幅和长线潜力",), spotlight.problems)

    def test_empty_history_reports_problem_instead_of_marking_everything_new(self) -> None:
        records = {"top_trending_v4": [_record(10, 1)]}

        spotlight = _build(records, {})

        self.assertEqual((), spotlight.all_new_faces)
        self.assertEqual(("还没有可用的历史快照，今天不判断新面孔和在线涨幅",), spotlight.problems)

    def test_missing_yesterday_is_not_replaced_by_another_day(self) -> None:
        records = {"top_trending_v4": [_record(10, 1, playing=9000)]}
        # 只有前天的快照：前天到今天涨了 3 倍，但不能当成“较昨天”。
        history: GameTrendHistory = {1: [_snapshot(_day(2), 3000)]}

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": {1}}, market=_flat_market(1, 2, 3))

        self.assertEqual((), spotlight.all_growth)
        self.assertEqual(
            (
                "缺少昨天的游戏或大盘快照，今天不判断较昨天的在线涨幅",
                "缺少 3 天前的游戏或大盘快照，今天不判断较 3 天前的在线涨幅",
            ),
            spotlight.problems,
        )

    def test_missing_market_snapshot_blocks_ccu_evidence(self) -> None:
        records = {"top_trending_v4": [_record(10, 1, playing=9000)]}

        spotlight = _build(
            records,
            _history({1: {1: 3000}}),
            recent_place_ids={"top_trending_v4": {1}},
            market={_day(0): 1_000_000},
        )

        self.assertEqual((), spotlight.all_growth)
        self.assertIn("缺少昨天的游戏或大盘快照，今天不判断较昨天的在线涨幅", spotlight.problems)


class LongTermAndLeaderTests(unittest.TestCase):
    def _retention_history(
        self,
        place_id: int,
        *,
        ccu: int,
        past_ccu: int,
        average_ccu: int | None,
        daily_visits: int,
        new_up: int = 95,
        new_down: int = 5,
    ) -> tuple[GameDailySnapshot, list[GameDailySnapshot]]:
        """当天快照与前两天快照：单局时长 = 日均 CCU × 1440 ÷ 日新增访问，好评率取新增投票。"""

        today = _snapshot(_day(0), ccu, 10_000_000, 1000 + new_up, 100 + new_down, average_ccu=average_ccu)
        history = [
            _snapshot(_day(1), past_ccu, 10_000_000 - daily_visits, 1000, 100),
            _snapshot(_day(2), past_ccu, 10_000_000 - 2 * daily_visits, 900, 90),
        ]
        return today, history

    def _build_steady(self, games: dict[int, dict]) -> MarketSpotlight:
        """这些游戏都新进热门榜（增长快），在线变化不大，只看留存结论。"""

        records = {
            "top_trending_v4": [
                _record(index + 1, place_id, playing=params["ccu"]) for index, (place_id, params) in enumerate(games.items())
            ]
        }
        snapshots: dict[int, GameDailySnapshot] = {}
        history: GameTrendHistory = {FILLER_PLACE_ID: [_snapshot(_day(1), 1)]}
        for place_id, params in games.items():
            snapshots[place_id], history[place_id] = self._retention_history(place_id, **params)
        return _build(
            records,
            history,
            recent_place_ids={"top_trending_v4": {99}},
            snapshots=snapshots,
        )

    def test_retention_tiers_follow_session_peak_and_rating(self) -> None:
        # 日新增访问 1,000,000 时，日均 CCU 20,000 约 29 分钟，4,000 约 6 分钟，100,000 为 144 分钟（疑似挂机）。
        spotlight = self._build_steady(
            {
                1: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 20000, "daily_visits": 1_000_000},
                2: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 20000, "daily_visits": 720_000},
                3: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 4000, "daily_visits": 1_000_000},
                4: {"ccu": 9000, "past_ccu": 30000, "average_ccu": 20000, "daily_visits": 1_000_000},
                5: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 20000, "daily_visits": 1_000_000, "new_up": 70, "new_down": 30},
                6: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 10000, "daily_visits": 1_000_000},
                7: {"ccu": 26000, "past_ccu": 28000, "average_ccu": 100_000, "daily_visits": 1_000_000},
                8: {"ccu": 9000, "past_ccu": 30000, "average_ccu": None, "daily_visits": 1_000_000},
            }
        )

        retention = _retention_by_place(spotlight, self, range(1, 9))
        self.assertEqual(
            {1: "good", 2: "good", 3: "bad", 4: "bad", 5: "bad", 6: "watch", 7: "watch", 8: "bad"},
            {place_id: verdict.tier for place_id, verdict in retention.items()},
        )
        # 好评率高不加分，只在偏低时判留不住。
        self.assertAlmostEqual(0.7, retention[5].like_ratio)
        self.assertEqual((None, "afk"), (retention[7].session_minutes, retention[7].session_note))
        self.assertEqual((None, "missing"), (retention[8].session_minutes, retention[8].session_note))
        self.assertAlmostEqual(40.0, retention[2].session_minutes)
        self.assertAlmostEqual(26000 / 28000, retention[1].peak_ratio)

    def test_long_term_skips_games_shown_on_card_but_keeps_hidden_growth(self) -> None:
        # 9 款都新进热门榜、在线持平、留得住；增长快只展示前 8 款，第 9 款可以出现在长线潜力栏。
        # 长线潜力按单局时长排序的情况见 test_long_term_sorts_by_session_minutes。
        games = range(1, 10)
        records = {"top_trending_v4": [_record(place_id, place_id, playing=30000 - place_id * 100) for place_id in games]}
        snapshots: dict[int, GameDailySnapshot] = {}
        history: GameTrendHistory = {}
        for place_id in games:
            ccu = 30000 - place_id * 100
            snapshots[place_id], history[place_id] = self._retention_history(
                place_id, ccu=ccu, past_ccu=ccu, average_ccu=20000, daily_visits=1_000_000
            )

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": {99}}, snapshots=snapshots)

        self.assertEqual([9], _ids(spotlight.growth_overflow))
        self.assertEqual([9], _ids(spotlight.long_term))

    def test_long_term_sorts_by_session_minutes(self) -> None:
        # 两款都已在榜、在线持平、没有增长证据，只能出现在长线潜力栏。
        records = {"top_trending_v4": [_record(1, 1, playing=26000), _record(2, 2, playing=25000)]}
        snapshots: dict[int, GameDailySnapshot] = {}
        history: GameTrendHistory = {}
        for place_id, daily_visits in ((1, 1_000_000), (2, 720_000)):
            ccu = records["top_trending_v4"][place_id - 1].playing
            snapshots[place_id], history[place_id] = self._retention_history(
                place_id, ccu=ccu, past_ccu=ccu, average_ccu=20000, daily_visits=daily_visits
            )

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": {1, 2}}, snapshots=snapshots)

        self.assertEqual((), spotlight.all_growth)
        self.assertEqual([2, 1], _ids(spotlight.long_term))
        self.assertAlmostEqual(40.0, spotlight.long_term[0].retention.session_minutes)

    def test_manual_run_before_scheduled_brief_skips_cross_day_comparisons(self) -> None:
        # 当天快照还没存进历史：此刻的访问与昨天 09:10 相减不足一天，单局时长会被放大，所以不判断。
        records = {"top_playing_now": [_record(9, 1, playing=26000)]}
        today, history = self._retention_history(1, ccu=26000, past_ccu=26000, average_ccu=20000, daily_visits=600_000)
        history.append(_snapshot(_day(7), 20000))

        manual = _build(
            records,
            {1: history},
            recent_place_ids={"top_playing_now": {1}},
            snapshots={1: today},
            scheduled=False,
        )
        scheduled = _build(records, {1: list(history)}, recent_place_ids={"top_playing_now": {1}}, snapshots={1: today})

        self.assertTrue(manual.before_scheduled_snapshot)
        self.assertIsNone(manual.new_game_leaders[0].retention)
        self.assertIsNone(manual.new_game_leaders[0].leader.state)
        self.assertFalse([problem for problem in manual.problems if "头部新游" in problem])
        self.assertFalse(scheduled.before_scheduled_snapshot)
        self.assertEqual("good", scheduled.new_game_leaders[0].retention.tier)
        self.assertEqual("up", scheduled.new_game_leaders[0].leader.state)

    def test_retention_requires_enough_recorded_days(self) -> None:
        records = {"top_trending_v4": [_record(3, 5, playing=8000)]}

        spotlight = _build(records, _history({5: {1: 7000}}), recent_place_ids={"top_trending_v4": {5}})

        self.assertEqual((), spotlight.long_term)
        self.assertEqual(2, spotlight.long_term_recorded_days)
        self.assertIsNone(spotlight.new_game_leaders[0].retention if spotlight.new_game_leaders else None)

    def test_earning_movement_tracks_previous_and_week_ranks(self) -> None:
        records = {"top_earning": [_record(149, 50)]}

        spotlight = _build(
            records,
            _history({50: {1: 5000, 2: 5000}}),
            previous_ranks={"top_earning": {50: 170}},
            recent_place_ids={"top_earning": {50}},
            oldest_ranks={"top_earning": {50: 75}},
        )

        earning = spotlight.growth_standout.earning
        self.assertEqual((149, 21, -74, False), (earning.rank, earning.change, earning.week_change, earning.entered_this_week))

    def test_leaders_are_top_new_games_on_playing_board_with_week_trend(self) -> None:
        records = {
            "top_playing_now": [
                _record(9, 1, playing=57000),
                _record(12, 2, playing=40000),
                _record(30, 3, playing=30000),
                _record(40, 4, playing=20000),
                _record(1, 5, created_at=OLD, playing=900000),
            ],
            # 1 当天新进热门榜，属于增长快；头部新游趋势不和其他栏去重，照样列出。
            "top_trending_v4": [_record(5, 1, playing=57000)],
        }
        history = _history(
            {
                1: {1: 55000, 7: 50000},
                2: {1: 42000, 7: 50000},
                4: {1: 20000, 7: 19500},
            }
        )

        spotlight = _build(
            records,
            history,
            recent_place_ids={"top_playing_now": {1, 2, 3, 4, 5}, "top_trending_v4": {9}},
        )

        self.assertEqual([1], _ids(spotlight.all_growth))
        # 3 近 14 天没上过榜，同时是新面孔。
        self.assertEqual([3], _ids(spotlight.all_new_faces))
        self.assertEqual([1, 2, 3], _ids(spotlight.new_game_leaders))
        statuses = [entry.leader for entry in spotlight.new_game_leaders]
        self.assertEqual([9, 12, 30], [status.rank for status in statuses])
        self.assertEqual(["up", "down", "new"], [status.state for status in statuses])
        self.assertEqual((57000, 50000), (statuses[0].ccu, statuses[0].ccu_week_ago))
        self.assertAlmostEqual(0.14, statuses[0].week_change)
        self.assertAlmostEqual(-0.2, statuses[1].week_change)
        self.assertEqual((30000, None, None), (statuses[2].ccu, statuses[2].ccu_week_ago, statuses[2].week_change))
        self.assertFalse([problem for problem in spotlight.problems if "头部新游" in problem])

    def test_leader_trend_within_ten_percent_is_flat(self) -> None:
        records = {"top_playing_now": [_record(9, 1, playing=54000)]}

        spotlight = _build(records, _history({1: {1: 54000, 7: 50000}}), recent_place_ids={"top_playing_now": {1}})

        self.assertEqual("flat", spotlight.new_game_leaders[0].leader.state)

    def test_missing_week_ago_day_skips_leader_trend_and_reports_problem(self) -> None:
        records = {"top_playing_now": [_record(9, 1, playing=57000)]}
        # 只有昨天和 6 天前的快照，上周同日（7 天前）整天没有：不改用 6 天前顶替。
        history = _history({1: {1: 55000, 6: 30000}})

        spotlight = _build(records, history, recent_place_ids={"top_playing_now": {1}})

        status = spotlight.new_game_leaders[0].leader
        self.assertEqual((None, None, None), (status.state, status.ccu_week_ago, status.week_change))
        self.assertIn("缺少 7 天前（上周同日）的快照，今天不判断头部新游趋势", spotlight.problems)

    def test_unreadable_history_does_not_add_a_second_leader_problem(self) -> None:
        records = {"top_playing_now": [_record(9, 1, playing=57000)]}

        spotlight = _build(records, None, recent_place_ids={"top_playing_now": {1}})

        self.assertIsNone(spotlight.new_game_leaders[0].leader.state)
        self.assertEqual(("游戏每日快照读取失败，今天不判断新面孔、在线涨幅和长线潜力",), spotlight.problems)


class GenreWindTests(unittest.TestCase):
    def test_new_game_genre_counts_ignore_old_and_small_games(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 11, genre="Simulation", playing=6000),
                _record(2, 12, genre="Obby", playing=4000),
                _record(3, 15, genre="Simulation", playing=900000),
                # 未标品类的新游计入总款数（占比的分母），但不算任何品类。
                _record(4, 16, genre="", playing=5000),
                # 老牌大作和体量不够的新游都不算。
                _record(5, 13, created_at=OLD, genre="Action RPG", playing=250000),
                _record(6, 14, genre="RPG", playing=2000),
            ],
            # 同一款游戏出现在多个榜单只算一款。
            "top_playing_now": [_record(1, 15, genre="Simulation", playing=900000)],
        }

        counts = build_new_game_genre_counts(records_by_sheet)

        self.assertEqual(({"Simulation": 2, "Obby": 1}, 4), (counts.counts, counts.total))

    def test_share_counts_games_not_ccu(self) -> None:
        # 一款 90 万在线的大作只算一款：Simulation 2 款、Obby 2 款，各占 50%。
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 11, genre="Simulation", playing=900000),
                _record(2, 12, genre="Simulation", playing=4000),
                _record(3, 13, genre="Obby", playing=4000),
                _record(4, 14, genre="Obby", playing=4000),
            ],
        }

        lines = build_genre_wind_lines(records_by_sheet, None)

        self.assertEqual(
            ("新游款数占比前 2：Obby 2 款 50%、Simulation 2 款 50%（历史数据积累中，暂不判断多少）",),
            lines,
        )

    def test_new_face_cluster_needs_three_games_and_thirty_percent(self) -> None:
        records_by_sheet = {"top_trending_v4": [_record(1, 21, genre="Obby")]}

        clustered = build_genre_wind_lines(records_by_sheet, ["Tycoon", "Tycoon", "Tycoon", "Obby", "RPG", "Sim"])
        too_few = build_genre_wind_lines(records_by_sheet, ["Tycoon", "Tycoon", "Obby"])
        too_spread = build_genre_wind_lines(records_by_sheet, ["Tycoon"] * 3 + [f"G{index}" for index in range(8)])

        self.assertEqual("今日新面孔 6 款中 3 款是 Tycoon", clustered[0])
        self.assertEqual(1, len(too_few))
        self.assertEqual(1, len(too_spread))

    def test_share_changes_against_yesterday(self) -> None:
        records_by_sheet = {"top_trending_v4": _genre_records(Tycoon=6, Obby=3, RPG=1)}
        # 昨天 20 款：Tycoon 4 款 20%、Obby 12 款 60%、RPG 4 款 20%。
        pulse = _pulse(day_before=({"Tycoon": 4, "Obby": 12, "RPG": 4}, 20))

        lines = build_genre_wind_lines(records_by_sheet, None, pulse)

        self.assertEqual(
            (
                "新游款数占比较昨天变化：Tycoon 20% → 60%（+40 个百分点，现 6 款）、"
                "Obby 60% → 30%（-30 个百分点，现 3 款）",
            ),
            lines,
        )

    def test_share_changes_fall_back_to_week(self) -> None:
        records_by_sheet = {"top_trending_v4": _genre_records(Tycoon=6, Obby=4)}

        lines = build_genre_wind_lines(
            records_by_sheet,
            None,
            _pulse(day_before=({"Tycoon": 59, "Obby": 41}, 100), week_before=({"Tycoon": 4, "Obby": 6}, 10)),
        )

        self.assertEqual(
            ("新游款数占比较上周同日变化：Tycoon 40% → 60%（+20 个百分点，现 6 款）、Obby 60% → 40%（-20 个百分点，现 4 款）",),
            lines,
        )

    def test_stable_shares_show_history_reference_preferring_week(self) -> None:
        records_by_sheet = {"top_trending_v4": _genre_records(Tycoon=6, Obby=3, RPG=1)}
        day_only = _pulse(day_before=({"Tycoon": 58, "Obby": 32, "RPG": 10}, 100))
        with_week = _pulse(
            day_before=({"Tycoon": 58, "Obby": 32, "RPG": 10}, 100),
            week_before=({"Tycoon": 57, "Obby": 34, "RPG": 9}, 100),
        )

        self.assertEqual(
            ("新游格局稳定，款数占比前 3：Tycoon 6 款 60%（昨天 58%）、Obby 3 款 30%（昨天 32%）、RPG 1 款 10%（昨天 10%）",),
            build_genre_wind_lines(records_by_sheet, None, day_only),
        )
        # 有上周同日时用上周同日作参照。
        self.assertEqual(
            (
                "新游格局稳定，款数占比前 3：Tycoon 6 款 60%（上周同日 57%）、Obby 3 款 30%（上周同日 34%）、"
                "RPG 1 款 10%（上周同日 9%）",
            ),
            build_genre_wind_lines(records_by_sheet, None, with_week),
        )

    def test_snapshots_without_counts_are_not_used_as_history(self) -> None:
        records_by_sheet = {"top_trending_v4": _genre_records(Tycoon=6, Obby=4)}
        # 只有旧口径（按 CCU）的快照解析后没有款数，不能拿来比。
        pulse = _pulse(day_before=({}, 0))

        lines = build_genre_wind_lines(records_by_sheet, None, pulse)

        self.assertEqual(("新游款数占比前 2：Tycoon 6 款 60%、Obby 4 款 40%（历史数据积累中，暂不判断多少）",), lines)


def _genre_records(**count_by_genre: int) -> list[GameRecord]:
    """按“品类=款数”构造新游，place_id 与排名依次递增。"""

    records: list[GameRecord] = []
    for genre, count in count_by_genre.items():
        for _ in range(count):
            index = len(records) + 1
            records.append(_record(index, 100 + index, genre=genre))
    return records


def _pulse(
    *,
    day_before: tuple[dict[str, int], int] | None = None,
    week_before: tuple[dict[str, int], int] | None = None,
) -> MarketPulse:
    """day_before / week_before 为（各品类款数, 新游总款数）。"""

    def snapshot(day: str, counts: tuple[dict[str, int], int] | None) -> MarketCcuSnapshot | None:
        if counts is None:
            return None
        return MarketCcuSnapshot(day, 0, 0, 0, new_game_genre_counts=counts[0], new_game_count=counts[1])

    current = MarketCcuSnapshot(_day(0), 0, 0, 0)
    return MarketPulse(
        snapshot=current,
        head_day_change=None,
        head_week_change=None,
        broad_day_change=None,
        broad_week_change=None,
        recorded_days=1,
        day_before=snapshot(_day(1), day_before),
        week_before=snapshot(_day(7), week_before),
    )


def _retention_by_place(spotlight: MarketSpotlight, test: unittest.TestCase, place_ids) -> dict:
    """从各栏里找出指定游戏的留存结论；这些游戏都应能找到。"""

    entries = {
        entry.place_id: entry
        for entry in (
            *spotlight.all_new_faces,
            *spotlight.all_growth,
            *spotlight.long_term,
            *spotlight.new_game_leaders,
        )
    }
    missing = [place_id for place_id in place_ids if place_id not in entries]
    test.assertFalse(missing, f"找不到这些游戏：{missing}")
    return {place_id: entries[place_id].retention for place_id in place_ids}


if __name__ == "__main__":
    unittest.main()
