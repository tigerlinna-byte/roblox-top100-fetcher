from __future__ import annotations

import unittest

from app.config import Config
from app.models import GameRecord
from app.top_trending_sheet import (
    calculate_rank_change,
    build_default_sheet_specs,
    build_top_trending_values,
    get_previous_ranks,
)


class TopTrendingSheetTests(unittest.TestCase):
    def test_build_values_uses_expected_compact_columns(self) -> None:
        cfg = Config(
            feishu_timezone="Asia/Shanghai",
            run_trigger_source="feishu_chat_command",
            run_trigger_actor="ou_test",
        )
        rows = build_top_trending_values(
            cfg,
            "top_trending_v4",
            [
                GameRecord(
                    rank=1,
                    place_id=123,
                    name="Trending A",
                    creator="Studio A",
                    playing=123456,
                    visits=987654321,
                    up_votes=999,
                    down_votes=1,
                    fetched_at="2026-03-09T00:00:00Z",
                    updated_at="2026-03-08T12:00:00Z",
                )
            ],
            {123: 4},
        )

        self.assertEqual(
            ["排名", "游戏名", "在线", "排名变化", "访问量", "开发者", "更新"],
            rows[0],
        )
        self.assertEqual(1, rows[1][0])
        self.assertEqual("123.5K", rows[1][2])
        self.assertEqual(3, rows[1][3])
        self.assertEqual("987.7M", rows[1][4])
        self.assertEqual("2026-03-08", rows[1][6])

    def test_calculate_rank_change_handles_first_entry(self) -> None:
        record = GameRecord(
            rank=3,
            place_id=999,
            name="Trending A",
            creator="Studio A",
            playing=10,
            visits=10,
            up_votes=0,
            down_votes=0,
            fetched_at="2026-03-09T00:00:00Z",
        )
        self.assertEqual("-", calculate_rank_change({}, record))

    def test_default_sheet_specs_follow_requested_order(self) -> None:
        specs = build_default_sheet_specs()

        self.assertEqual(
            ["top_trending_v4", "up_and_coming_v4", "ccu_based_v1"],
            [item["title"] for item in specs],
        )
        self.assertEqual(
            ["Top_Trending_V4", "Up_And_Coming_V4", "CCU_Based_V1"],
            [item["sort_id"] for item in specs],
        )

    def test_get_previous_ranks_parses_each_sheet_variable(self) -> None:
        cfg = Config(
            feishu_top_trending_prev_ranks='{"101":1,"102":2}',
            feishu_up_and_coming_prev_ranks='{"201":5}',
            feishu_ccu_based_prev_ranks="",
        )

        previous_ranks = get_previous_ranks(cfg)

        self.assertEqual({101: 1, 102: 2}, previous_ranks["top_trending_v4"])
        self.assertEqual({201: 5}, previous_ranks["up_and_coming_v4"])
        self.assertEqual({}, previous_ranks["ccu_based_v1"])

    def test_data_rows_keep_same_column_representation(self) -> None:
        cfg = Config()
        rows = build_top_trending_values(
            cfg,
            "top_trending_v4",
            [
                GameRecord(
                    rank=1,
                    place_id=101,
                    name="Game A",
                    creator="Studio A",
                    playing=123456,
                    visits=987654321,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-09T00:00:00Z",
                    updated_at="2026-03-08T12:00:00Z",
                ),
                GameRecord(
                    rank=2,
                    place_id=102,
                    name="Game B",
                    creator="Studio B",
                    playing=4321,
                    visits=654321,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-09T00:00:00Z",
                    updated_at="2026-03-07T12:00:00Z",
                ),
            ],
            {101: 3, 102: 2},
        )

        self.assertIsInstance(rows[1][0], int)
        self.assertIsInstance(rows[2][0], int)
        self.assertIsInstance(rows[1][1], str)
        self.assertIsInstance(rows[2][1], str)
        self.assertIsInstance(rows[1][2], str)
        self.assertIsInstance(rows[2][2], str)
        self.assertIsInstance(rows[1][4], str)
        self.assertIsInstance(rows[2][4], str)
        self.assertIsInstance(rows[1][6], str)
        self.assertIsInstance(rows[2][6], str)


if __name__ == "__main__":
    unittest.main()
