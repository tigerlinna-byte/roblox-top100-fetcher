from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import Mock

from app.config import Config
from app.models import GameRecord
from app.top_trending_sheet import (
    MIN_RENDER_ROWS,
    build_launch_date_cells,
    build_rank_change_cells,
    calculate_game_name_width,
    calculate_rank_change,
    build_default_sheet_specs,
    build_display_name,
    build_top_trending_values,
    get_previous_ranks,
    get_saved_spreadsheet_target,
    resolve_spreadsheet_variables,
    save_spreadsheet_target,
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
                    universe_id=123,
                    place_id=123,
                    name="Trending A",
                    localized_name="趋势A",
                    thumbnail_url="https://t1.example/trending-a.png",
                    creator="Studio A",
                    playing=123456,
                    visits=987654321,
                    up_votes=999,
                    down_votes=1,
                    fetched_at="2026-03-09T00:00:00Z",
                    created_at="2026-03-01T12:00:00Z",
                    updated_at="2026-03-08T12:00:00Z",
                )
            ],
            {123: 4},
        )

        self.assertEqual(
            ["排名", "缩略图", "游戏名", "在线", "排名变化", "访问量", "开发者", "首次上线"],
            rows[0],
        )
        self.assertEqual(1, rows[1][0])
        self.assertEqual("https://t1.example/trending-a.png", rows[1][1])
        self.assertEqual("Trending A 趋势A", rows[1][2])
        self.assertEqual("123.5K", rows[1][3])
        self.assertEqual(3, rows[1][4])
        self.assertEqual("987.7M", rows[1][5])
        self.assertEqual(date(2026, 3, 1), rows[1][7])

    def test_build_display_name_appends_localized_name(self) -> None:
        record = GameRecord(
            rank=1,
            universe_id=1,
            place_id=1,
            name="Game A",
            localized_name="游戏A",
            fetched_at="2026-03-09T00:00:00Z",
        )

        self.assertEqual("Game A 游戏A", build_display_name(record))

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
        self.assertEqual("进榜", calculate_rank_change({}, record))

    def test_build_rank_change_cells_maps_colors(self) -> None:
        records = [
            GameRecord(
                rank=1,
                place_id=101,
                name="Game A",
                creator="Studio A",
                playing=10,
                visits=10,
                up_votes=0,
                down_votes=0,
                fetched_at="2026-03-09T00:00:00Z",
            ),
            GameRecord(
                rank=5,
                place_id=102,
                name="Game B",
                creator="Studio B",
                playing=10,
                visits=10,
                up_votes=0,
                down_votes=0,
                fetched_at="2026-03-09T00:00:00Z",
            ),
            GameRecord(
                rank=3,
                place_id=103,
                name="Game C",
                creator="Studio C",
                playing=10,
                visits=10,
                up_votes=0,
                down_votes=0,
                fetched_at="2026-03-09T00:00:00Z",
            ),
        ]

        cells = build_rank_change_cells(
            records,
            {
                101: 3,
                102: 2,
                103: 3,
            },
        )

        self.assertEqual((2, 2, "red"), (cells[0].row_index, cells[0].value, cells[0].color))
        self.assertEqual((3, -3, "green"), (cells[1].row_index, cells[1].value, cells[1].color))
        self.assertEqual((4, 0, "black"), (cells[2].row_index, cells[2].value, cells[2].color))

    def test_build_launch_date_cells_maps_age_ranges(self) -> None:
        cells = build_launch_date_cells(
            [
                GameRecord(
                    rank=1,
                    place_id=1,
                    name="New Game",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-10T00:00:00Z",
                    created_at="2026-02-10T00:00:00Z",
                ),
                GameRecord(
                    rank=2,
                    place_id=2,
                    name="Quarter Game",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-10T00:00:00Z",
                    created_at="2025-11-15T00:00:00Z",
                ),
                GameRecord(
                    rank=3,
                    place_id=3,
                    name="Old Game",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-10T00:00:00Z",
                    created_at="2025-08-01T00:00:00Z",
                ),
                GameRecord(
                    rank=4,
                    place_id=4,
                    name="Very Old Game",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-10T00:00:00Z",
                    created_at="2024-12-31T00:00:00Z",
                ),
            ]
        )

        self.assertEqual((2, "green"), (cells[0].row_index, cells[0].color))
        self.assertEqual((3, "yellow"), (cells[1].row_index, cells[1].color))
        self.assertEqual((4, "black"), (cells[2].row_index, cells[2].color))
        self.assertEqual((5, "gray"), (cells[3].row_index, cells[3].color))

    def test_default_sheet_specs_follow_requested_order(self) -> None:
        specs = build_default_sheet_specs()

        self.assertEqual(
            ["top_trending_v4", "up_and_coming_v4", "top_playing_now"],
            [item["title"] for item in specs],
        )
        self.assertEqual(
            ["Top_Trending_V4", "Up_And_Coming_V4", "top-playing-now"],
            [item["sort_id"] for item in specs],
        )

    def test_get_previous_ranks_parses_each_sheet_variable(self) -> None:
        cfg = Config(
            feishu_top_trending_prev_ranks='{"101":1,"102":2}',
            feishu_up_and_coming_prev_ranks='{"201":5}',
            feishu_top_playing_now_prev_ranks='{"301":7}',
        )

        previous_ranks = get_previous_ranks(cfg)

        self.assertEqual({101: 1, 102: 2}, previous_ranks["top_trending_v4"])
        self.assertEqual({201: 5}, previous_ranks["up_and_coming_v4"])
        self.assertEqual({301: 7}, previous_ranks["top_playing_now"])

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
                    created_at="2026-03-01T12:00:00Z",
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
                    created_at="2026-02-01T12:00:00Z",
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
        self.assertIsInstance(rows[1][3], str)
        self.assertIsInstance(rows[2][3], str)
        self.assertIsInstance(rows[1][5], str)
        self.assertIsInstance(rows[2][5], str)
        self.assertIsInstance(rows[1][7], date)
        self.assertIsInstance(rows[2][7], date)

    def test_values_are_padded_to_clear_old_tail_rows(self) -> None:
        rows = build_top_trending_values(
            Config(),
            "top_trending_v4",
            [],
            {},
        )

        self.assertEqual(MIN_RENDER_ROWS, len(rows))
        self.assertEqual(["排名", "缩略图", "游戏名", "在线", "排名变化", "访问量", "开发者", "首次上线"], rows[0])
        self.assertEqual(["", "", "", "", "", "", "", ""], rows[-1])

    def test_game_name_width_tracks_visual_length(self) -> None:
        narrow = calculate_game_name_width(
            [
                GameRecord(
                    rank=1,
                    place_id=1,
                    name="Game",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-09T00:00:00Z",
                )
            ]
        )
        wide = calculate_game_name_width(
            [
                GameRecord(
                    rank=1,
                    place_id=1,
                    name="超长中文游戏名 Roblox Ultimate Adventure Simulator",
                    creator="Studio",
                    playing=1,
                    visits=1,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-09T00:00:00Z",
                )
            ]
        )

        self.assertGreater(wide, narrow)

    def test_compact_number_uses_sub_thousand_k_suffix(self) -> None:
        rows = build_top_trending_values(
            Config(),
            "top_trending_v4",
            [
                GameRecord(
                    rank=1,
                    place_id=1,
                    name="Game",
                    creator="Studio",
                    playing=900,
                    visits=950,
                    up_votes=0,
                    down_votes=0,
                    fetched_at="2026-03-09T00:00:00Z",
                )
            ],
            {},
        )

        self.assertEqual("0.9K", rows[1][3])
        self.assertEqual("0.9K", rows[1][5])

    def test_get_previous_ranks_uses_test_variables_for_manual_runs(self) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            run_trigger_source="manual",
            feishu_top_trending_test_prev_ranks='{"401":9}',
            feishu_up_and_coming_test_prev_ranks='{"402":8}',
            feishu_top_playing_now_test_prev_ranks='{"403":7}',
        )

        previous_ranks = get_previous_ranks(cfg)

        self.assertEqual({401: 9}, previous_ranks["top_trending_v4"])
        self.assertEqual({402: 8}, previous_ranks["up_and_coming_v4"])
        self.assertEqual({403: 7}, previous_ranks["top_playing_now"])

    def test_resolve_spreadsheet_variables_routes_cron_to_formal_sheet(self) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            run_trigger_source="cloudflare_cron",
            feishu_top_trending_spreadsheet_title="Roblox Top 100",
        )

        variables = resolve_spreadsheet_variables(cfg)

        self.assertEqual("FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN", variables.spreadsheet_token_variable_name)
        self.assertEqual("Roblox Top 100", variables.spreadsheet_title)

    def test_resolve_spreadsheet_variables_routes_manual_to_test_sheet(self) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            run_trigger_source="manual",
            feishu_top_trending_test_spreadsheet_title="Roblox Top 100 Test",
        )

        variables = resolve_spreadsheet_variables(cfg)

        self.assertEqual("FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN", variables.spreadsheet_token_variable_name)
        self.assertEqual("Roblox Top 100 Test", variables.spreadsheet_title)

    def test_get_saved_spreadsheet_target_reads_test_sheet_ids(self) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            run_trigger_source="feishu_chat_command",
            feishu_top_trending_test_spreadsheet_token="shtcn_test",
            feishu_top_trending_test_sheet_id="sheet_test_1",
            feishu_up_and_coming_test_sheet_id="sheet_test_2",
            feishu_top_playing_now_test_sheet_id="sheet_test_3",
        )

        target = get_saved_spreadsheet_target(cfg)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual("shtcn_test", target.spreadsheet_token)
        self.assertEqual(
            ("sheet_test_1", "sheet_test_2", "sheet_test_3"),
            tuple(sheet.sheet_id for sheet in target.sheets),
        )

    def test_save_spreadsheet_target_persists_test_variable_names(self) -> None:
        cfg = Config(
            run_report_mode="top_trending_sheet",
            run_trigger_source="manual",
        )
        github_client = Mock()
        github_client.upsert_repository_variable.return_value = True
        variables = resolve_spreadsheet_variables(cfg)
        target = get_saved_spreadsheet_target(
            Config(
                run_report_mode="top_trending_sheet",
                run_trigger_source="manual",
                feishu_top_trending_test_spreadsheet_token="shtcn_test",
                feishu_top_trending_test_sheet_id="sheet_test_1",
                feishu_up_and_coming_test_sheet_id="sheet_test_2",
                feishu_top_playing_now_test_sheet_id="sheet_test_3",
            )
        )

        assert target is not None
        saved = save_spreadsheet_target(github_client, target, variables)

        self.assertTrue(saved)
        self.assertEqual(4, github_client.upsert_repository_variable.call_count)
        first_call = github_client.upsert_repository_variable.call_args_list[0].args
        self.assertEqual(
            ("FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN", "shtcn_test"),
            first_call,
        )


if __name__ == "__main__":
    unittest.main()
