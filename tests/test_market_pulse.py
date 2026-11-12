from __future__ import annotations

from datetime import date
import json
import unittest

from app.market_pulse import (
    MarketCcuSnapshot,
    build_market_ccu_snapshot,
    build_market_pulse,
    merge_market_ccu_history,
    parse_market_ccu_history,
    serialize_market_ccu_history,
)
from app.models import GameRecord


def _snapshot(snapshot_date: str, head: int, broad: int) -> MarketCcuSnapshot:
    return MarketCcuSnapshot(snapshot_date=snapshot_date, head_ccu=head, broad_ccu=broad, game_count=100)


class MarketPulseTests(unittest.TestCase):
    def test_snapshot_sums_head_and_broad_ranges_by_rank(self) -> None:
        records = [GameRecord(rank=rank, name=f"G{rank}", playing=rank * 100) for rank in range(1, 13)]

        snapshot = build_market_ccu_snapshot(records, date(2026, 10, 27))

        self.assertEqual("2026-10-27", snapshot.snapshot_date)
        self.assertEqual(sum(rank * 100 for rank in range(1, 11)), snapshot.head_ccu)
        self.assertEqual(sum(rank * 100 for rank in range(1, 13)), snapshot.broad_ccu)
        self.assertEqual(12, snapshot.game_count)

    def test_snapshot_keeps_every_new_game_genre_count(self) -> None:
        playing = [GameRecord(rank=1, name="P", playing=100)]

        snapshot = build_market_ccu_snapshot(playing, date(2026, 11, 12), {"Tycoon": 28, "Obby": 5, "RPG": 1}, 40)

        # 只有一款的品类也保留，否则历史里会被当成 0 款。
        self.assertEqual({"Tycoon": 28, "Obby": 5, "RPG": 1}, snapshot.new_game_genre_counts)
        self.assertEqual(40, snapshot.new_game_count)

    def test_genre_counts_round_trip_and_old_ccu_shares_are_ignored(self) -> None:
        snapshot = MarketCcuSnapshot("2026-11-13", 1, 2, 3, new_game_genre_counts={"Tycoon": 28}, new_game_count=159)
        raw = serialize_market_ccu_history([snapshot])
        # 旧字段按 CCU 算占比，口径不同，直接忽略：11-12 的新游品类 CCU 占比、更早的热门榜品类 CCU 占比。
        legacy = (
            '{"history":[{"snapshot_date":"2026-11-12","head_ccu":1,"broad_ccu":2,"game_count":3,'
            '"new_game_genre_permille":{"Tycoon":235}},'
            '{"snapshot_date":"2026-11-11","head_ccu":1,"broad_ccu":2,"game_count":3,'
            '"trending_genre_permille":{"Action RPG":190}}]}'
        )

        self.assertEqual([snapshot], parse_market_ccu_history(raw))
        parsed = parse_market_ccu_history(legacy)
        self.assertEqual([({}, 0), ({}, 0)], [(item.new_game_genre_counts, item.new_game_count) for item in parsed])
        rewritten = serialize_market_ccu_history(parsed)
        self.assertNotIn("trending_genre_permille", rewritten)
        self.assertNotIn("new_game_genre_permille", rewritten)

    def test_pulse_exposes_day_and_week_compare_snapshots(self) -> None:
        history = [_snapshot("2026-10-26", 100, 1000), _snapshot("2026-10-20", 100, 1000)]

        pulse = build_market_pulse(_snapshot("2026-10-27", 100, 1000), history)

        self.assertEqual("2026-10-26", pulse.day_before.snapshot_date)
        self.assertEqual("2026-10-20", pulse.week_before.snapshot_date)

    def test_merge_keeps_first_snapshot_of_same_day_and_trims_old_days(self) -> None:
        history = [
            _snapshot("2026-10-27", 100, 1000),
            _snapshot("2026-09-20", 100, 1000),
        ]

        merged = merge_market_ccu_history(history, _snapshot("2026-10-27", 999, 9999))

        self.assertEqual(["2026-10-27"], [item.snapshot_date for item in merged])
        self.assertEqual(100, merged[0].head_ccu)

    def test_history_round_trip_and_invalid_payload(self) -> None:
        history = [_snapshot("2026-10-27", 1, 2), _snapshot("2026-10-26", 3, 4)]

        raw = serialize_market_ccu_history(history)

        self.assertEqual(history, parse_market_ccu_history(raw))
        self.assertEqual([], parse_market_ccu_history("not json"))
        self.assertEqual([], parse_market_ccu_history(json.dumps({"history": [{"snapshot_date": "bad"}]})))

    def test_pulse_compares_with_yesterday_and_same_day_last_week(self) -> None:
        history = [
            _snapshot("2026-10-26", 1000, 10000),
            _snapshot("2026-10-20", 1000, 8000),
        ]

        pulse = build_market_pulse(_snapshot("2026-10-27", 1050, 11500), history)

        self.assertEqual("flat", pulse.head_day_change.trend)
        self.assertEqual("up", pulse.broad_day_change.trend)
        self.assertAlmostEqual(0.15, pulse.broad_day_change.change_ratio)
        self.assertEqual("up", pulse.broad_week_change.trend)
        self.assertEqual("2026-10-20", pulse.broad_week_change.compare_date)
        self.assertEqual(3, pulse.recorded_days)

    def test_pulse_without_history_reports_accumulation(self) -> None:
        pulse = build_market_pulse(_snapshot("2026-10-27", 1000, 10000), [])

        self.assertIsNone(pulse.broad_day_change)
        self.assertIsNone(pulse.broad_week_change)
        self.assertEqual(1, pulse.recorded_days)

    def test_pulse_prefers_recorded_same_day_snapshot(self) -> None:
        history = [_snapshot("2026-10-27", 500, 5000), _snapshot("2026-10-26", 500, 5000)]

        pulse = build_market_pulse(_snapshot("2026-10-27", 900, 9000), history)

        self.assertEqual(5000, pulse.snapshot.broad_ccu)
        self.assertEqual("flat", pulse.broad_day_change.trend)


if __name__ == "__main__":
    unittest.main()
