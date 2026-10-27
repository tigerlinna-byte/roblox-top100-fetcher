from __future__ import annotations

import unittest

from app.market_spotlight import build_genre_wind_lines, build_market_spotlight
from app.models import GameRecord


FETCHED_AT = "2026-10-27T01:00:00Z"


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
