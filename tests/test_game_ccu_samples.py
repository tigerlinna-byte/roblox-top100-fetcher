from __future__ import annotations

from datetime import date
import json
import unittest
from unittest.mock import patch

from app.config import Config
from app.game_ccu_samples import (
    CcuSampleWindow,
    add_ccu_sample,
    attach_ccu_summaries,
    build_ccu_sample_window,
    describe_ccu_sample_problem,
    is_sampled_recently,
    parse_ccu_sample_window,
    serialize_ccu_sample_window,
)
from app.game_trend_history import GameDailySnapshot
from app.github_client import GitHubClientError, RepositoryFile
from app.main import _run_ccu_sample
from app.models import GameRecord
from app.roblox_client import RobloxClientError


TODAY = date(2026, 11, 5)


def _snapshot(ccu: int) -> GameDailySnapshot:
    return GameDailySnapshot(snapshot_date=TODAY.isoformat(), ccu=ccu, visits=0, up_votes=0, down_votes=0)


def _window(window_date: str = "2026-11-04", samples: int = 3) -> CcuSampleWindow:
    return CcuSampleWindow(
        window_date=window_date,
        place_ids_by_universe={100: 1, 200: 2},
        sampled_at=tuple(f"2026-11-04T{hour:02d}:10:00Z" for hour in (7, 13, 19)[:samples]),
        ccu_by_place={1: (1000, 2000, 3000)[:samples]},
    )


class CcuSampleWindowTests(unittest.TestCase):
    def test_window_lists_universes_of_snapshot_games_only(self) -> None:
        records_by_sheet = {
            "top_playing_now": [
                GameRecord(rank=1, name="a", universe_id=100, place_id=1),
                GameRecord(rank=2, name="old", universe_id=300, place_id=3),
            ],
            "top_earning": [GameRecord(rank=1, name="a", universe_id=100, place_id=1)],
        }

        window = build_ccu_sample_window(records_by_sheet, {1: _snapshot(5)}, TODAY)

        self.assertEqual("2026-11-05", window.window_date)
        self.assertEqual({100: 1}, window.place_ids_by_universe)

    def test_serialize_and_parse_round_trip(self) -> None:
        window = _window()

        self.assertEqual(window, parse_ccu_sample_window(serialize_ccu_sample_window(window)))

    def test_parse_returns_none_for_malformed_content(self) -> None:
        for raw in ("not json", "[]", '{"version":1,"games":{}}', '{"window_date":"bad","universes":{},"sampled_at":[],"games":{}}'):
            self.assertIsNone(parse_ccu_sample_window(raw))

    def test_add_sample_ignores_games_outside_the_list(self) -> None:
        window = CcuSampleWindow(window_date="2026-11-04", place_ids_by_universe={100: 1})

        updated = add_ccu_sample(window, {100: 50, 999: 7}, "2026-11-04T07:10:00Z")
        updated = add_ccu_sample(updated, {100: 60}, "2026-11-04T13:10:00Z")

        self.assertEqual({1: (50, 60)}, updated.ccu_by_place)
        self.assertEqual(3, updated.sample_count)

    def test_repeated_trigger_within_an_hour_is_detected(self) -> None:
        window = _window()

        self.assertTrue(is_sampled_recently(window, "2026-11-04T19:40:00Z"))
        self.assertFalse(is_sampled_recently(window, "2026-11-04T20:10:00Z"))
        self.assertFalse(is_sampled_recently(CcuSampleWindow("2026-11-04", {}), "2026-11-04T20:10:00Z"))


class AttachCcuSummaryTests(unittest.TestCase):
    def test_average_and_peak_include_the_brief_own_ccu(self) -> None:
        attached = attach_ccu_summaries({1: _snapshot(6000)}, _window(), TODAY)

        self.assertEqual((3000, 6000, 4), (attached[1].average_ccu, attached[1].peak_ccu, attached[1].ccu_sample_count))
        self.assertEqual(6000, attached[1].ccu)

    def test_games_with_too_few_samples_get_no_average(self) -> None:
        attached = attach_ccu_summaries({1: _snapshot(6000), 2: _snapshot(70)}, _window(samples=1), TODAY)

        self.assertIsNone(attached[1].average_ccu)
        self.assertIsNone(attached[2].average_ccu)

    def test_three_samples_are_enough(self) -> None:
        attached = attach_ccu_summaries({1: _snapshot(3000)}, _window(samples=2), TODAY)

        self.assertEqual((2000, 3000, 3), (attached[1].average_ccu, attached[1].peak_ccu, attached[1].ccu_sample_count))

    def test_stale_or_same_day_windows_are_not_used(self) -> None:
        snapshots = {1: _snapshot(6000)}

        self.assertIs(snapshots, attach_ccu_summaries(snapshots, _window("2026-11-02"), TODAY))
        self.assertIs(snapshots, attach_ccu_summaries(snapshots, _window("2026-11-05"), TODAY))
        self.assertIs(snapshots, attach_ccu_summaries(snapshots, None, TODAY))


class DescribeCcuSampleProblemTests(unittest.TestCase):
    def test_reports_actual_sample_count(self) -> None:
        self.assertEqual("", describe_ccu_sample_problem(_window(samples=3), TODAY))
        self.assertEqual("CCU 采样 3/4 次，时长可能有偏差", describe_ccu_sample_problem(_window(samples=2), TODAY))
        self.assertEqual("CCU 采样 2/4 次，时长暂不计分", describe_ccu_sample_problem(_window(samples=1), TODAY))

    def test_stale_window_is_reported(self) -> None:
        self.assertEqual(
            "CCU 采样窗口已过期（2026-11-02），时长暂不计分",
            describe_ccu_sample_problem(_window("2026-11-02"), TODAY),
        )

    def test_rollout_and_same_day_rerun_are_not_problems(self) -> None:
        self.assertEqual("", describe_ccu_sample_problem(None, TODAY))
        self.assertEqual("", describe_ccu_sample_problem(_window("2026-11-05", samples=0), TODAY))


class RunCcuSampleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(
            run_report_mode="ccu_sample",
            run_trigger_source="cloudflare_cron",
            output_dir="./data",
        )
        for target, attribute in (
            ("app.main.GitHubClient", "github_client"),
            ("app.main.RobloxClient", "roblox_client"),
            ("app.main.FeishuClient", "feishu_client"),
            ("app.main.write_json_document", "write_document"),
            ("app.main.now_iso", "now_iso"),
        ):
            patcher = patch(target)
            setattr(self, attribute, patcher.start())
            self.addCleanup(patcher.stop)
        self.now_iso.return_value = "2026-11-04T19:10:00Z"
        self.github_client.return_value.get_repository_file.return_value = RepositoryFile(
            content=serialize_ccu_sample_window(_window(samples=2)),
            sha="abc",
        )
        self.roblox_client.return_value.fetch_ccu_by_universe.return_value = {100: 3000}

    def test_scheduled_run_appends_sample_without_notifying(self) -> None:
        self.assertEqual(0, _run_ccu_sample(self.cfg))

        put = self.github_client.return_value.put_repository_file
        path, content = put.call_args.args
        self.assertEqual("game_ccu_samples.json", path)
        self.assertEqual("data-history", put.call_args.kwargs["branch"])
        self.assertEqual("abc", put.call_args.kwargs["sha"])
        payload = json.loads(content)
        self.assertEqual([1000, 2000, 3000], payload["games"]["1"])
        self.assertEqual("2026-11-04T19:10:00Z", payload["sampled_at"][-1])
        self.feishu_client.assert_not_called()

    def test_manual_run_does_not_write(self) -> None:
        cfg = Config(**{**self.cfg.__dict__, "run_trigger_source": "manual"})

        self.assertEqual(0, _run_ccu_sample(cfg))

        self.roblox_client.return_value.fetch_ccu_by_universe.assert_called_once()
        self.write_document.assert_called_once()
        self.github_client.return_value.put_repository_file.assert_not_called()

    def test_no_window_yet_is_not_a_failure(self) -> None:
        self.github_client.return_value.get_repository_file.return_value = None

        self.assertEqual(0, _run_ccu_sample(self.cfg))

        self.roblox_client.return_value.fetch_ccu_by_universe.assert_not_called()

    def test_repeated_trigger_skips_sampling(self) -> None:
        self.now_iso.return_value = "2026-11-04T13:30:00Z"

        self.assertEqual(0, _run_ccu_sample(self.cfg))

        self.roblox_client.return_value.fetch_ccu_by_universe.assert_not_called()
        self.github_client.return_value.put_repository_file.assert_not_called()

    def test_failures_fail_the_run_without_writing_or_notifying(self) -> None:
        self.roblox_client.return_value.fetch_ccu_by_universe.side_effect = RobloxClientError("boom")
        with self.assertLogs(level="ERROR"):
            self.assertEqual(1, _run_ccu_sample(self.cfg))
        self.github_client.return_value.put_repository_file.assert_not_called()

        self.roblox_client.return_value.fetch_ccu_by_universe.side_effect = None
        self.github_client.return_value.put_repository_file.side_effect = GitHubClientError("403")
        with self.assertLogs(level="ERROR"):
            self.assertEqual(1, _run_ccu_sample(self.cfg))

        self.github_client.return_value.get_repository_file.side_effect = GitHubClientError("boom")
        with self.assertLogs(level="ERROR"):
            self.assertEqual(1, _run_ccu_sample(self.cfg))
        self.feishu_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
