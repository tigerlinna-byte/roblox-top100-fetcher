from __future__ import annotations

from datetime import date
import unittest

from app.models import GameRecord
from app.top_trending_briefing import (
    TrendingBriefingEntry,
    build_top_trending_briefing_markdown,
    collect_top_trending_briefing_entries,
)


class TopTrendingBriefingTests(unittest.TestCase):
    def test_collect_entries_filters_to_new_recent_games_and_merges_sheet_labels(self) -> None:
        records_by_sheet = {
            "top_trending_v4": [
                GameRecord(
                    rank=5,
                    place_id=101,
                    name="Game A",
                    localized_name="游戏A",
                    playing=12345,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-02-01T00:00:00Z",
                ),
                GameRecord(
                    rank=10,
                    place_id=102,
                    name="Old Game",
                    playing=2000,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2025-10-01T00:00:00Z",
                ),
            ],
            "up_and_coming_v4": [
                GameRecord(
                    rank=3,
                    place_id=101,
                    name="Game A",
                    localized_name="游戏A",
                    playing=12500,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-02-01T00:00:00Z",
                ),
                GameRecord(
                    rank=8,
                    place_id=103,
                    name="Existing Game",
                    playing=3000,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-03-01T00:00:00Z",
                ),
            ],
            "top_playing_now": [
                GameRecord(
                    rank=2,
                    place_id=101,
                    name="Game A",
                    localized_name="游戏A",
                    playing=13000,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-02-01T00:00:00Z",
                )
            ],
        }
        previous_ranks_by_sheet = {
            "top_trending_v4": {},
            "up_and_coming_v4": {},
            "top_playing_now": {"101": 7},  # type: ignore[dict-item]
        }

        entries = collect_top_trending_briefing_entries(records_by_sheet, previous_ranks_by_sheet)

        self.assertEqual(
            [
                TrendingBriefingEntry(
                    place_id=101,
                    name="Game A 游戏A",
                    ccu=13000,
                    launch_date=date(2026, 2, 1),
                    sheet_labels=("热门榜", "新秀榜", "在玩榜"),
                    best_rank=2,
                ),
                TrendingBriefingEntry(
                    place_id=103,
                    name="Existing Game",
                    ccu=3000,
                    launch_date=date(2026, 3, 1),
                    sheet_labels=("新秀榜",),
                    best_rank=8,
                ),
            ],
            entries,
        )

    def test_build_markdown_includes_briefing_and_sheet_link(self) -> None:
        markdown = build_top_trending_briefing_markdown(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=1,
                        place_id=201,
                        name="Game B",
                        playing=6789,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-03-10T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [],
                "top_playing_now": [],
            },
            {
                "top_trending_v4": {},
                "up_and_coming_v4": {},
                "top_playing_now": {},
            },
            "https://feishu.cn/sheets/test",
        )

        self.assertIn("## 今日关注", markdown)
        self.assertIn("Game B｜热门榜｜CCU 6,789｜首次上线 2026-03-10", markdown)
        self.assertNotIn("查看完整榜单", markdown)

    def test_build_markdown_handles_no_focus_games(self) -> None:
        markdown = build_top_trending_briefing_markdown(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=1,
                        place_id=301,
                        name="Existing Game",
                        playing=5000,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-03-01T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [],
                "top_playing_now": [],
            },
            {
                "top_trending_v4": {301: 2},
                "up_and_coming_v4": {},
                "top_playing_now": {},
            },
            "https://feishu.cn/sheets/test",
        )

        self.assertIn("今天没有发现新上榜且首次上线未满 3 个月的重点游戏。", markdown)


if __name__ == "__main__":
    unittest.main()
