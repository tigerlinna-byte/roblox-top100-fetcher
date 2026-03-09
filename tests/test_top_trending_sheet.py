from __future__ import annotations

import unittest

from app.config import Config
from app.models import GameRecord
from app.top_trending_sheet import (
    SORT_SHEETS,
    build_default_sheet_specs,
    build_top_trending_summary,
    build_top_trending_values,
    format_like_rate,
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
        )

        self.assertEqual(
            ["排名", "游戏名", "在线人数", "点赞率", "总访问量", "开发者", "更新时间"],
            rows[4],
        )
        self.assertEqual("99.9%", rows[5][3])
        self.assertEqual("2026-03-08T12:00:00Z", rows[5][6])

    def test_format_like_rate_handles_zero_votes(self) -> None:
        self.assertEqual("-", format_like_rate(0, 0))

    def test_build_summary_contains_sheet_link(self) -> None:
        cfg = Config(
            feishu_timezone="Asia/Shanghai",
            run_trigger_source="feishu_chat_command",
            run_trigger_actor="ou_test",
        )
        summary = build_top_trending_summary(
            cfg,
            {
                "top_trending_v4": [
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
                    )
                ],
                "up_and_coming_v4": [],
                "ccu_based_v1": [],
            },
            "https://feishu.cn/sheets/shtcn_test",
        )

        self.assertIn("Top Trending 系列表已写入飞书表格。", summary)
        self.assertIn("top_trending_v4: 1 条，榜首 Trending A / 在线 123456", summary)
        self.assertIn("表格: https://feishu.cn/sheets/shtcn_test", summary)

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


if __name__ == "__main__":
    unittest.main()
