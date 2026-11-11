from __future__ import annotations

from datetime import date
import unittest

from app.game_trend_history import (
    GameDailySnapshot,
    build_game_daily_snapshots,
    build_game_trend_metrics,
    merge_game_trend_history,
    parse_game_trend_history,
    serialize_game_trend_history,
)
from app.models import GameRecord


TODAY = date(2026, 10, 27)


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


def _record(rank: int, place_id: int, *, created_at: str, playing: int, visits: int = 0) -> GameRecord:
    return GameRecord(rank=rank, place_id=place_id, name=f"Game {place_id}", playing=playing, visits=visits, created_at=created_at)


class GameDailySnapshotTests(unittest.TestCase):
    def test_snapshots_keep_recent_games_within_considered_rank(self) -> None:
        records_by_sheet = {
            "top_playing_now": [
                _record(5, 1, created_at="2026-10-01T00:00:00Z", playing=30000, visits=500),
                _record(8, 2, created_at="2020-01-01T00:00:00Z", playing=90000),
            ],
            "top_earning": [
                _record(40, 1, created_at="2026-10-01T00:00:00Z", playing=30500, visits=400),
                _record(150, 3, created_at="2026-10-20T00:00:00Z", playing=1000),
                _record(280, 4, created_at="2026-10-20T00:00:00Z", playing=500),
            ],
            "top_trending_v4": [_record(150, 5, created_at="2026-10-20T00:00:00Z", playing=800)],
        }

        snapshots = build_game_daily_snapshots(records_by_sheet, TODAY)

        # 老游戏不记录；收入榜看到前 300 名，其他榜单只看前 100 名；同一游戏多榜取最大值。
        self.assertEqual({1, 3, 4}, set(snapshots))
        self.assertEqual(_snapshot("2026-10-27", 30500, 500), snapshots[1])


class GameTrendHistoryStorageTests(unittest.TestCase):
    def test_merge_keeps_first_snapshot_of_day_and_trims_old_days(self) -> None:
        history = {
            1: [_snapshot("2026-10-27", 100), _snapshot("2026-10-01", 50)],
            2: [_snapshot("2026-10-02", 70)],
        }

        merged = merge_game_trend_history(history, {1: _snapshot("2026-10-27", 999), 3: _snapshot("2026-10-27", 5)}, TODAY)

        self.assertEqual({1: [_snapshot("2026-10-27", 100)], 3: [_snapshot("2026-10-27", 5)]}, merged)

    def test_serialize_and_parse_round_trip(self) -> None:
        history = {7: [_snapshot("2026-10-27", 10, 20, 3, 1), _snapshot("2026-10-26", 9, 15, 2, 1)]}

        self.assertEqual(history, parse_game_trend_history(serialize_game_trend_history(history)))

    def test_samples_round_trip_alongside_old_snapshots(self) -> None:
        history = {7: [_snapshot("2026-10-27", 10, 20, 3, 1, average_ccu=8), _snapshot("2026-10-26", 9, 15, 2, 1)]}

        serialized = serialize_game_trend_history(history)

        self.assertIn('[["2026-10-27",10,20,3,1,8,16,4],["2026-10-26",9,15,2,1]]', serialized)
        self.assertEqual(history, parse_game_trend_history(serialized))

    def test_parse_ignores_malformed_content(self) -> None:
        self.assertEqual({}, parse_game_trend_history("not json"))
        self.assertEqual(
            {1: [_snapshot("2026-10-27", 1, 2, 3, 4)]},
            parse_game_trend_history('{"games":{"1":[["2026-10-27",1,2,3,4],["bad"]],"x":[]}}'),
        )


class GameTrendMetricsTests(unittest.TestCase):
    def test_metrics_from_consecutive_daily_snapshots(self) -> None:
        history = [
            _snapshot("2026-10-26", 20000, 9_000_000, 9000, 280),
            _snapshot("2026-10-25", 22000, 8_000_000, 8000, 260),
            _snapshot("2026-10-24", 28000, 7_000_000, 6000, 500),
        ]
        today = _snapshot("2026-10-27", 26000, 10_000_000, 9700, 300, average_ccu=23000)

        metrics = build_game_trend_metrics(today, history)

        self.assertEqual(4, metrics.recorded_days)
        self.assertAlmostEqual(26000 / ((28000 + 22000 + 20000) / 3) - 1, metrics.ccu_change_ratio)
        self.assertAlmostEqual(26000 / 28000, metrics.peak_ratio)
        self.assertEqual(4, metrics.board_streak_days)
        # 全天平均 CCU 23000 × 1440 ÷ 日新增访问 1,000,000
        self.assertAlmostEqual(33.12, metrics.session_minutes)
        self.assertFalse(metrics.session_samples_missing)
        self.assertEqual((23000, 46000, 4), (metrics.average_ccu, metrics.peak_ccu, metrics.ccu_sample_count))
        self.assertAlmostEqual(700 / 720, metrics.like_ratio)
        self.assertTrue(metrics.like_ratio_is_recent)
        self.assertAlmostEqual(0.97 - 6000 / 6500, metrics.like_ratio_change)

    def test_peak_window_ignores_the_extra_day_kept_for_new_face_lookback(self) -> None:
        # 快照保留 15 天，峰值窗口只看含当天在内的 14 天：14 天前的高点不参与。
        history = [_snapshot("2026-10-14", 30000), _snapshot("2026-10-13", 90000)]

        metrics = build_game_trend_metrics(_snapshot("2026-10-27", 24000), history)

        self.assertAlmostEqual(24000 / 30000, metrics.peak_ratio)

    def test_missing_samples_skip_session_instead_of_using_single_ccu(self) -> None:
        history = [_snapshot("2026-10-26", 20000, 9_000_000)]
        today = _snapshot("2026-10-27", 26000, 10_000_000)

        metrics = build_game_trend_metrics(today, history)

        self.assertIsNone(metrics.session_minutes)
        self.assertTrue(metrics.session_samples_missing)

    def test_first_day_on_board_is_not_reported_as_missing_samples(self) -> None:
        metrics = build_game_trend_metrics(_snapshot("2026-10-27", 26000, 10_000_000), [])

        self.assertIsNone(metrics.session_minutes)
        self.assertFalse(metrics.session_samples_missing)

    def test_long_gap_skips_session_and_falls_back_to_cumulative_rating(self) -> None:
        history = [_snapshot("2026-10-20", 5000, 1000, 100, 100)]
        today = _snapshot("2026-10-27", 6000, 5000, 900, 100)

        metrics = build_game_trend_metrics(today, history)

        self.assertIsNone(metrics.session_minutes)
        self.assertIsNone(metrics.ccu_change_ratio)
        self.assertAlmostEqual(0.9, metrics.like_ratio)
        self.assertFalse(metrics.like_ratio_is_recent)
        self.assertEqual(1, metrics.board_streak_days)

    def test_rerun_on_same_day_uses_recorded_snapshot(self) -> None:
        recorded_today = _snapshot("2026-10-27", 1000)

        metrics = build_game_trend_metrics(_snapshot("2026-10-27", 5000), [recorded_today])

        self.assertEqual(1000, metrics.ccu)
        self.assertEqual(1, metrics.recorded_days)


if __name__ == "__main__":
    unittest.main()
