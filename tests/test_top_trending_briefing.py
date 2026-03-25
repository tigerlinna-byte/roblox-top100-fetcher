from __future__ import annotations

from datetime import date
import unittest

from app.models import GameRecord
from app.top_trending_briefing import (
    TrendingBriefingEntry,
    build_top_trending_briefing_card,
    build_top_trending_briefing_markdown,
    collect_top_trending_briefing_entries,
    collect_top_trending_focus_place_ids_by_sheet,
)


class TopTrendingBriefingTests(unittest.TestCase):
    def test_collect_entries_filters_to_new_recent_games_and_only_keeps_new_sheet_labels(self) -> None:
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
            "top_trending_v4": set(),
            "up_and_coming_v4": set(),
            "top_playing_now": {101},
        }

        entries = collect_top_trending_briefing_entries(records_by_sheet, previous_ranks_by_sheet)

        self.assertEqual(
            [
                TrendingBriefingEntry(
                    place_id=101,
                    name="Game A 游戏A",
                    genre="",
                    ccu=13000,
                    launch_date=date(2026, 2, 1),
                    sheet_rank_labels=("热门榜 #5", "新秀榜 #3"),
                    best_rank=2,
                ),
                TrendingBriefingEntry(
                    place_id=103,
                    name="Existing Game",
                    genre="",
                    ccu=3000,
                    launch_date=date(2026, 3, 1),
                    sheet_rank_labels=("新秀榜 #8",),
                    best_rank=8,
                ),
            ],
            entries,
        )

    def test_collect_focus_place_ids_by_sheet_only_marks_new_sheet(self) -> None:
        focus_place_ids_by_sheet = collect_top_trending_focus_place_ids_by_sheet(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=5,
                        place_id=101,
                        name="Game A",
                        playing=12345,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-02-01T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [
                    GameRecord(
                        rank=3,
                        place_id=101,
                        name="Game A",
                        playing=12500,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-02-01T00:00:00Z",
                    )
                ],
                "top_playing_now": [
                    GameRecord(
                        rank=2,
                        place_id=101,
                        name="Game A",
                        playing=13000,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-02-01T00:00:00Z",
                    )
                ],
            },
            {
                "top_trending_v4": set(),
                "up_and_coming_v4": set(),
                "top_playing_now": {101},
            },
        )

        self.assertEqual({101}, focus_place_ids_by_sheet["top_trending_v4"])
        self.assertEqual({101}, focus_place_ids_by_sheet["up_and_coming_v4"])
        self.assertNotIn("top_playing_now", focus_place_ids_by_sheet)

    def test_build_markdown_includes_dated_title_and_briefing(self) -> None:
        markdown = build_top_trending_briefing_markdown(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=1,
                        place_id=201,
                        name="Game B",
                        genre="Survival",
                        playing=6789,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-03-10T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [],
                "top_playing_now": [],
            },
            {
                "top_trending_v4": set(),
                "up_and_coming_v4": set(),
                "top_playing_now": set(),
            },
            "https://feishu.cn/sheets/test",
        )

        self.assertIn("## 今日关注（2026-03-14）", markdown)
        self.assertIn("Game B｜Survival｜热门榜 #1｜CCU 6,789｜首次上线 2026-03-10", markdown)
        self.assertNotIn("查看完整榜单", markdown)

    def test_build_card_highlights_intro_and_game_name(self) -> None:
        card = build_top_trending_briefing_card(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=1,
                        place_id=201,
                        name="Game B",
                        localized_name="游戏B",
                        genre="Survival",
                        playing=6789,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-03-10T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [],
                "top_playing_now": [],
            },
            {
                "top_trending_v4": set(),
                "up_and_coming_v4": set(),
                "top_playing_now": set(),
            },
        )

        self.assertEqual("今日关注（2026-03-14）", card["header"]["title"]["content"])
        content = card["elements"][0]["content"]
        self.assertIn("**以下游戏为新上榜且首次上线未满 3 个月，建议优先关注：**", content)
        self.assertIn("<font color='blue'>Game B 游戏B</font>", content)
        self.assertIn("｜Survival｜", content)
        self.assertIn("<font color='red'>热门榜 #1</font>", content)

    def test_briefing_limits_visible_entries_to_ten(self) -> None:
        records = [
            GameRecord(
                rank=index,
                place_id=1000 + index,
                name=f"Game {index}",
                playing=1000 + index,
                fetched_at="2026-03-14T00:00:00Z",
                created_at="2026-03-10T00:00:00Z",
            )
            for index in range(1, 13)
        ]
        records_by_sheet = {
            "top_trending_v4": records,
            "up_and_coming_v4": [],
            "top_playing_now": [],
        }
        previous_ranks_by_sheet = {
            "top_trending_v4": set(),
            "up_and_coming_v4": set(),
            "top_playing_now": set(),
        }

        markdown = build_top_trending_briefing_markdown(
            records_by_sheet,
            previous_ranks_by_sheet,
            "https://feishu.cn/sheets/test",
        )
        card = build_top_trending_briefing_card(
            records_by_sheet,
            previous_ranks_by_sheet,
        )

        self.assertIn("Game 10", markdown)
        self.assertNotIn("Game 11", markdown)
        self.assertIn("其余值得关注的游戏请直接查看下方表格。", markdown)
        self.assertIn("其余值得关注的游戏请直接查看下方表格。", card["elements"][0]["content"])

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
                "top_trending_v4": {301},
                "up_and_coming_v4": set(),
                "top_playing_now": set(),
            },
            "https://feishu.cn/sheets/test",
        )

        self.assertIn("今天没有发现新上榜且首次上线未满 3 个月的重点游戏。", markdown)

    def test_collect_entries_excludes_games_seen_within_last_week(self) -> None:
        entries = collect_top_trending_briefing_entries(
            {
                "top_trending_v4": [
                    GameRecord(
                        rank=1,
                        place_id=401,
                        name="Recent Return",
                        playing=5000,
                        fetched_at="2026-03-14T00:00:00Z",
                        created_at="2026-03-10T00:00:00Z",
                    )
                ],
                "up_and_coming_v4": [],
                "top_playing_now": [],
            },
            {
                "top_trending_v4": {401},
                "up_and_coming_v4": set(),
                "top_playing_now": set(),
            },
        )

        self.assertEqual([], entries)


if __name__ == "__main__":
    unittest.main()
