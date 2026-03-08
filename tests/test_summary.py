from __future__ import annotations

import unittest

from app.config import Config
from app.models import GameRecord
from app.summary import build_failure_markdown, build_success_markdown


class SummaryTests(unittest.TestCase):
    def test_success_markdown_contains_top_section(self) -> None:
        cfg = Config(
            feishu_timezone="Asia/Shanghai",
            run_trigger_source="schedule",
            run_trigger_actor="github-actions",
        )
        records = [
            GameRecord(
                rank=1,
                place_id=123,
                name="Game A",
                creator="Studio A",
                playing=9999,
                visits=50000,
                up_votes=1000,
                down_votes=10,
                fetched_at="2026-03-08T00:00:00Z",
            ),
            GameRecord(
                rank=2,
                place_id=124,
                name="Game B",
                creator="Studio B",
                playing=8888,
                visits=40000,
                up_votes=900,
                down_votes=9,
                fetched_at="2026-03-08T00:00:00Z",
            ),
        ]

        content = build_success_markdown(cfg, records)

        self.assertIn("# Roblox 排行榜同步成功", content)
        self.assertIn("- 触发: schedule (github-actions)", content)
        self.assertIn("## Top 10", content)
        self.assertIn("1. Game A | 在线 9999", content)
        self.assertIn("2. Game B | 在线 8888", content)

    def test_failure_markdown_contains_reason(self) -> None:
        cfg = Config(feishu_timezone="Asia/Shanghai", run_trigger_source="manual")
        content = build_failure_markdown(cfg, "webhook 失败")

        self.assertIn("# Roblox 排行榜任务失败", content)
        self.assertIn("- 触发: manual", content)
        self.assertIn("webhook 失败", content)


if __name__ == "__main__":
    unittest.main()
