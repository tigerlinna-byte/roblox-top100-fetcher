from __future__ import annotations

import unittest

from app.game_trend_history import GameDailySnapshot
from app.market_spotlight import build_genre_wind_lines, build_market_spotlight
from app.models import GameRecord


FETCHED_AT = "2026-10-27T01:00:00Z"


def _snapshot(day: str, ccu: int, visits: int = 0, up: int = 0, down: int = 0) -> GameDailySnapshot:
    return GameDailySnapshot(snapshot_date=day, ccu=ccu, visits=visits, up_votes=up, down_votes=down)


def _record(rank: int, place_id: int, *, created_at: str, playing: int = 1000, genre: str = "Simulation") -> GameRecord:
    return GameRecord(
        rank=rank,
        place_id=place_id,
        name=f"Game {place_id}",
        genre=genre,
        playing=playing,
        fetched_at=FETCHED_AT,
        created_at=created_at,
    )


class MarketSpotlightTests(unittest.TestCase):
    def test_standout_is_highest_scoring_fresh_game_with_reasons(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(4, 1, created_at="2026-10-18T00:00:00Z", playing=62000),
                _record(30, 2, created_at="2026-06-01T00:00:00Z", playing=5000),
            ],
            "top_earning": [_record(17, 1, created_at="2026-10-18T00:00:00Z", playing=62000)],
        }
        previous_ranks = {"top_trending_v4": {1: 45, 2: 75}, "top_earning": {1: 60}}
        recent_place_ids = {"top_trending_v4": {1, 2}, "top_earning": {1}}

        spotlight = build_market_spotlight(records_by_sheet, previous_ranks, recent_place_ids)

        self.assertEqual(1, spotlight.standout.place_id)
        reasons = [signal.reason for signal in spotlight.standout.signals]
        self.assertEqual(["上线 9 天", "新进收入榜前 20", "收入榜较上次 ↑43", "同时在 2 个榜单"], reasons)
        # 新游 3 + 收入榜新进 3 + 飙升 (2 + 1 个额外步长) + 多榜 1
        self.assertEqual(10, spotlight.standout.score)
        self.assertEqual([2], [entry.place_id for entry in spotlight.entries])
        self.assertEqual(3, spotlight.entries[0].score)

    def test_established_games_on_many_sheets_are_not_listed(self) -> None:
        old_game = _record(1, 9, created_at="2023-01-01T00:00:00Z", playing=900000)
        records_by_sheet = {
            "top_trending_v4": [old_game],
            "top_playing_now": [old_game],
            "top_earning": [old_game],
        }
        previous_ranks = {"top_trending_v4": {9: 1}, "top_playing_now": {9: 1}, "top_earning": {9: 1}}
        recent_place_ids = {"top_trending_v4": {9}, "top_playing_now": {9}, "top_earning": {9}}

        spotlight = build_market_spotlight(records_by_sheet, previous_ranks, recent_place_ids)

        self.assertIsNone(spotlight.standout)
        self.assertEqual((), spotlight.entries)

    def test_no_standout_when_best_score_below_threshold(self) -> None:
        records_by_sheet = {"top_trending_v4": [_record(50, 3, created_at="2026-05-01T00:00:00Z")]}
        previous_ranks = {"top_trending_v4": {3: 70}}
        recent_place_ids = {"top_trending_v4": {3}}

        spotlight = build_market_spotlight(records_by_sheet, previous_ranks, recent_place_ids)

        self.assertIsNone(spotlight.standout)
        self.assertEqual([3], [entry.place_id for entry in spotlight.entries])

    def test_ranks_beyond_considered_range_are_ignored(self) -> None:
        records_by_sheet = {"top_earning": [_record(250, 4, created_at="2026-10-20T00:00:00Z")]}

        spotlight = build_market_spotlight(records_by_sheet, {}, {})

        self.assertIsNone(spotlight.standout)
        self.assertEqual((), spotlight.entries)

    def test_long_term_pick_is_scored_with_reasons_and_not_repeated(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 1, created_at="2026-10-20T00:00:00Z", playing=90000),
                _record(10, 2, created_at="2026-10-05T00:00:00Z", playing=26000),
            ],
            "top_earning": [
                _record(15, 1, created_at="2026-10-20T00:00:00Z", playing=90000),
                _record(50, 2, created_at="2026-10-05T00:00:00Z", playing=26000),
            ],
        }
        snapshots = {
            1: _snapshot("2026-10-27", 90000, 50_000_000, 1000, 500),
            2: _snapshot("2026-10-27", 26000, 10_000_000, 9700, 300),
        }
        history = {
            1: [_snapshot("2026-10-26", 30000, 20_000_000, 600, 300), _snapshot("2026-10-25", 3000, 1_000_000, 50, 20)],
            2: [
                _snapshot("2026-10-26", 20000, 9_000_000, 9000, 280),
                _snapshot("2026-10-25", 22000, 8_000_000, 8000, 260),
                _snapshot("2026-10-24", 28000, 7_000_000, 6000, 500),
            ],
        }

        spotlight = build_market_spotlight(records_by_sheet, {}, {}, snapshots, history)

        self.assertEqual(1, spotlight.standout.place_id)
        self.assertEqual([2], [entry.place_id for entry in spotlight.long_term])
        self.assertEqual((), spotlight.entries)
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
        # 爆发的游戏同样计算长线指标，卡片里用来区分昙花一现：单局只有约 3 分钟。
        self.assertEqual(4, spotlight.long_term_recorded_days)
        self.assertIn("估算时长 3 分钟", [signal.reason for signal in spotlight.standout.long_term_signals])

    def test_long_term_requires_enough_recorded_days(self) -> None:
        records_by_sheet = {"top_trending_v4": [_record(3, 5, created_at="2026-10-20T00:00:00Z", playing=8000)]}
        snapshots = {5: _snapshot("2026-10-27", 8000)}
        history = {5: [_snapshot("2026-10-26", 7000)]}

        spotlight = build_market_spotlight(records_by_sheet, {}, {}, snapshots, history)

        self.assertEqual((), spotlight.long_term)
        self.assertEqual(2, spotlight.long_term_recorded_days)
        self.assertEqual((), spotlight.standout.long_term_signals)

    def test_afk_sessions_and_collapsing_ccu_are_not_rewarded(self) -> None:
        records_by_sheet = {"top_trending_v4": [_record(3, 6, created_at="2026-10-20T00:00:00Z", playing=4000)]}
        snapshots = {6: _snapshot("2026-10-27", 4000, 1_010_000, 0, 0)}
        history = {
            6: [
                _snapshot("2026-10-26", 10000, 1_000_000),
                _snapshot("2026-10-25", 12000, 990_000),
            ]
        }

        spotlight = build_market_spotlight(records_by_sheet, {}, {}, snapshots, history)

        signals = {signal.kind: signal for signal in spotlight.standout.long_term_signals}
        self.assertEqual((-3, "在线较前 3 日 -64%"), (signals["ccu_trend"].score, signals["ccu_trend"].reason))
        self.assertEqual(-2, signals["peak_hold"].score)
        self.assertEqual((0, "疑似挂机，时长不计分"), (signals["session"].score, signals["session"].reason))

    def test_genre_wind_lines_describe_new_entries_and_trending_head(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 11, created_at="2026-09-01T00:00:00Z", genre="Simulation"),
                _record(2, 12, created_at="2026-09-01T00:00:00Z", genre="Simulation"),
                _record(3, 13, created_at="2026-09-01T00:00:00Z", genre="Obby"),
                _record(25, 14, created_at="2026-09-01T00:00:00Z", genre="Obby"),
            ],
        }

        lines = build_genre_wind_lines(records_by_sheet, {"top_trending_v4": set()})

        self.assertEqual(
            ("今日新上榜 4 款中 2 款是 Simulation", "热门榜前 20 名中 Simulation 占 2 款"),
            lines,
        )

    def test_genre_wind_skips_single_occurrences(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                _record(1, 21, created_at="2020-01-01T00:00:00Z", genre="Obby"),
                _record(2, 22, created_at="2020-01-01T00:00:00Z", genre="RPG"),
            ],
        }

        self.assertEqual((), build_genre_wind_lines(records_by_sheet, {"top_trending_v4": {21, 22}}))


if __name__ == "__main__":
    unittest.main()
