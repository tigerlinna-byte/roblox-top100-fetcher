from __future__ import annotations

import unittest
from datetime import date, timedelta

from app.game_trend_history import GameDailySnapshot, GameTrendHistory
from app.market_pulse import MarketCcuSnapshot, MarketPulse
from app.market_spotlight import MarketSpotlight, build_genre_wind_lines, build_market_spotlight
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
) -> MarketSpotlight:
    return build_market_spotlight(
        records_by_sheet,
        previous_ranks or {},
        recent_place_ids or {},
        snapshots if snapshots is not None else _snapshots(records_by_sheet),
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
        self.assertEqual((), spotlight.veteran_earners)

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
        self.assertEqual((), spotlight.veteran_earners)


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

    def test_old_games_with_earning_evidence_are_listed_separately(self) -> None:
        records = {
            "top_earning": [
                _record(31, 1, created_at=OLD, playing=31000),
                _record(60, 2, created_at=OLD, playing=50000),
            ]
        }

        spotlight = _build(
            records,
            _history({}),
            previous_ranks={"top_earning": {1: 212, 2: 61}},
            recent_place_ids={"top_earning": {1, 2}},
        )

        self.assertEqual([1], _ids(spotlight.veteran_earners))
        self.assertEqual(["收入榜 ↑181"], _evidence(spotlight.veteran_earners[0]))
        self.assertEqual((), spotlight.all_growth)


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
    def test_long_term_lists_steady_games_with_reasons(self) -> None:
        records = {
            "top_trending_v4": [_record(1, 1, playing=90000), _record(10, 2, playing=26000)],
            "top_earning": [_record(50, 2, playing=26000)],
        }
        snapshots = {
            1: _snapshot(_day(0), 90000, 50_000_000, 1000, 500, average_ccu=60000),
            2: _snapshot(_day(0), 26000, 10_000_000, 9700, 300, average_ccu=23000),
        }
        history = {
            1: [_snapshot(_day(1), 30000, 20_000_000, 600, 300), _snapshot(_day(2), 3000, 1_000_000, 50, 20)],
            2: [
                _snapshot(_day(1), 20000, 9_000_000, 9000, 280),
                _snapshot(_day(2), 22000, 8_000_000, 8000, 260),
                _snapshot(_day(3), 28000, 7_000_000, 6000, 500),
            ],
        }

        spotlight = _build(
            records,
            history,
            previous_ranks={"top_earning": {2: 50}},
            recent_place_ids={"top_trending_v4": {1, 2}, "top_earning": {2}},
            snapshots=snapshots,
        )

        self.assertEqual([1], _ids(spotlight.all_growth))
        self.assertEqual([2], _ids(spotlight.long_term))
        long_term = spotlight.long_term[0]
        self.assertEqual(
            [
                "在线较前 3 日 +11%",
                "较 14 日峰值 -7%",
                "估算时长 33 分钟",
                "新增好评 97%",
                "好评率较 3 日前 +4.7 个点",
                "收入榜 #50",
            ],
            [signal.reason for signal in long_term.long_term_signals],
        )
        # 趋势 1 + 峰值 2 + 时长 2 + 好评 1 + 好评走势 1 + 收入榜 1
        self.assertEqual(8, long_term.long_term_score)
        self.assertEqual(4, spotlight.long_term_recorded_days)
        self.assertEqual(
            (1002, 23000, 46000, 4),
            (long_term.universe_id, long_term.average_ccu, long_term.peak_ccu, long_term.ccu_sample_count),
        )
        # 增长快的游戏同样附带长线依据，用来区分昙花一现：单局只有约 3 分钟。
        growth_reasons = [signal.reason for signal in spotlight.growth_standout.long_term_signals]
        self.assertIn("估算时长 3 分钟", growth_reasons)

    def test_long_term_requires_enough_recorded_days(self) -> None:
        records = {"top_trending_v4": [_record(3, 5, playing=8000)]}

        spotlight = _build(records, _history({5: {1: 7000}}), recent_place_ids={"top_trending_v4": {5}})

        self.assertEqual((), spotlight.long_term)
        self.assertEqual(2, spotlight.long_term_recorded_days)

    def test_missing_samples_and_afk_sessions_do_not_score(self) -> None:
        records = {"top_trending_v4": [_record(3, 6, playing=4000), _record(4, 7, playing=8000)]}
        snapshots = {
            6: _snapshot(_day(0), 4000, 1_010_000, 0, 0, average_ccu=7000),
            7: _snapshot(_day(0), 8000, 2_000_000),
        }
        history = {
            6: [_snapshot(_day(1), 10000, 1_000_000), _snapshot(_day(2), 12000, 990_000)],
            7: [_snapshot(_day(1), 8000, 1_000_000), _snapshot(_day(2), 8000, 500_000)],
        }

        spotlight = _build(records, history, recent_place_ids={"top_trending_v4": {8}}, snapshots=snapshots)

        signals_by_place = {
            entry.place_id: {signal.kind: signal for signal in entry.long_term_signals}
            for entry in spotlight.all_growth
        }
        collapsing = signals_by_place[6]
        self.assertEqual((-3, "在线较前 3 日 -64%"), (collapsing["ccu_trend"].score, collapsing["ccu_trend"].reason))
        self.assertEqual(-2, collapsing["peak_hold"].score)
        self.assertEqual((0, "疑似挂机，时长不计分"), (collapsing["session"].score, collapsing["session"].reason))
        unsampled = signals_by_place[7]["session"]
        self.assertEqual((0, "时长样本不足"), (unsampled.score, unsampled.reason))

    def test_long_term_earning_follows_weekly_trend(self) -> None:
        records = {"top_earning": [_record(149, 50)]}

        spotlight = _build(
            records,
            _history({50: {1: 5000, 2: 5000}}),
            previous_ranks={"top_earning": {50: 170}},
            recent_place_ids={"top_earning": {50}},
            oldest_ranks={"top_earning": {50: 75}},
        )

        earning_signal = next(
            signal for signal in spotlight.growth_standout.long_term_signals if signal.kind == "earning"
        )
        self.assertEqual((-1, "收入榜 #149（一周 ↓74）"), (earning_signal.score, earning_signal.reason))
        self.assertEqual((21, -74, False), (
            spotlight.growth_standout.earning.change,
            spotlight.growth_standout.earning.week_change,
            spotlight.growth_standout.earning.entered_this_week,
        ))

    def test_leaders_are_steady_new_games_on_playing_board_with_status(self) -> None:
        records = {
            "top_playing_now": [
                _record(9, 1, playing=57000),
                _record(12, 2, playing=40000),
                _record(30, 3, playing=30000),
                _record(40, 4, playing=20000),
                _record(1, 5, created_at=OLD, playing=900000),
            ],
            # 有增长证据的游戏归增长快，不重复出现在头部新游。
            "top_trending_v4": [_record(5, 6, playing=25000)],
        }
        history = _history(
            {
                # 6 天前有过更高的峰值，长线分不达标，所以不会被归到长线潜力栏。
                1: {**{offset: 60000 for offset in range(1, 6)}, 6: 80000, 7: 50000},
                2: {1: 40000},
                3: {1: 30000},
                4: {1: 20000},
                6: {1: 25000},
            }
        )

        spotlight = _build(
            records,
            history,
            previous_ranks={"top_playing_now": {1: 8, 2: 12}},
            recent_place_ids={"top_playing_now": {1, 2, 3, 4, 5}, "top_trending_v4": {7}},
            oldest_ranks={"top_playing_now": {1: 13}},
        )

        self.assertEqual([6], _ids(spotlight.all_growth))
        self.assertEqual([1, 2, 3], _ids(spotlight.new_game_leaders))
        leader = spotlight.new_game_leaders[0].leader
        self.assertEqual((9, -1, 4), (leader.rank, leader.rank_day_change, leader.rank_week_change))
        self.assertAlmostEqual(-0.05, leader.ccu_day_change)
        self.assertAlmostEqual(0.14, leader.ccu_week_change)
        self.assertEqual((8, False, "up"), (leader.board_streak_days, leader.board_streak_capped, leader.state))
        # 没有上周同日的快照时，状态词看较昨天比大盘多涨多少。
        self.assertEqual("flat", spotlight.new_game_leaders[1].leader.state)

    def test_leader_streak_is_capped_at_lookback_window(self) -> None:
        records = {"top_playing_now": [_record(9, 1, playing=57000)]}
        history = _history({1: {**{offset: 57000 for offset in range(1, 15)}, 10: 90000}})

        spotlight = _build(records, history, recent_place_ids={"top_playing_now": {1}})

        leader = spotlight.new_game_leaders[0].leader
        self.assertEqual((14, True), (leader.board_streak_days, leader.board_streak_capped))


class GenreWindTests(unittest.TestCase):
    def test_genre_wind_lines_describe_new_faces_and_trending_share(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 11, genre="Simulation", playing=3000),
                _record(2, 12, genre="Simulation", playing=3000),
                _record(3, 13, genre="Obby", playing=2000),
                _record(25, 14, genre="Obby", playing=2000),
            ],
        }

        lines = build_genre_wind_lines(records_by_sheet, ["Simulation", "Obby", "Simulation", "Tycoon"])

        self.assertEqual(
            ("今日新面孔 4 款中 2 款是 Simulation", "热门榜 CCU 占比前 2：Simulation 60%、Obby 40%"),
            lines,
        )

    def test_genre_wind_skips_new_face_line_without_cluster_or_judgement(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [_record(1, 21, genre="Obby"), _record(2, 22, genre="RPG")],
        }

        single = build_genre_wind_lines(records_by_sheet, ["Obby", "RPG"])
        unjudged = build_genre_wind_lines(records_by_sheet, None)

        self.assertEqual(("热门榜 CCU 占比前 2：Obby 50%、RPG 50%",), single)
        self.assertEqual(single, unjudged)

    def test_genre_wind_reports_biggest_share_changes_against_yesterday(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 31, genre="Action RPG", playing=24000),
                _record(2, 32, genre="Tycoon", playing=13000),
                _record(3, 33, genre="Obby", playing=63000),
            ],
        }
        pulse = _pulse(day_before={"Action RPG": 90, "Tycoon": 230, "Obby": 610})

        lines = build_genre_wind_lines(records_by_sheet, None, pulse)

        self.assertEqual(
            (
                "热门榜 CCU 占比较昨天变化：Action RPG 9% → 24%（+15 个百分点，主要是 Game 31）、"
                "Tycoon 23% → 13%（-10 个百分点）",
            ),
            lines,
        )

    def test_genre_wind_falls_back_to_week_then_stable_top(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 41, genre="Tycoon", playing=6000),
                _record(2, 42, genre="Obby", playing=4000),
            ],
        }

        week_lines = build_genre_wind_lines(
            records_by_sheet,
            None,
            _pulse(day_before={"Tycoon": 590, "Obby": 410}, week_before={"Tycoon": 400, "Obby": 600}),
        )
        stable_lines = build_genre_wind_lines(records_by_sheet, None, _pulse(day_before={"Tycoon": 590, "Obby": 410}))

        self.assertEqual(
            ("热门榜 CCU 占比较上周同日变化：Tycoon 40% → 60%（+20 个百分点，主要是 Game 41）、Obby 60% → 40%（-20 个百分点）",),
            week_lines,
        )
        self.assertEqual(("格局稳定，热门榜 CCU 占比前 2：Tycoon 60%、Obby 40%",), stable_lines)


def _pulse(
    *,
    day_before: dict[str, int] | None = None,
    week_before: dict[str, int] | None = None,
) -> MarketPulse:
    def snapshot(day: str, permille: dict[str, int] | None) -> MarketCcuSnapshot | None:
        if permille is None:
            return None
        return MarketCcuSnapshot(day, 0, 0, 0, trending_genre_permille=permille)

    current = MarketCcuSnapshot("2026-10-27", 0, 0, 0)
    return MarketPulse(
        snapshot=current,
        head_day_change=None,
        head_week_change=None,
        broad_day_change=None,
        broad_week_change=None,
        recorded_days=1,
        day_before=snapshot("2026-10-26", day_before),
        week_before=snapshot("2026-10-20", week_before),
    )


if __name__ == "__main__":
    unittest.main()
