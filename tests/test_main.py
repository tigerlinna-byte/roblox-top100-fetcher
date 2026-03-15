from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.main import _notify_success
from app.models import GameRecord


class MainTests(unittest.TestCase):
    @patch("app.main._sync_top_trending_sheet")
    @patch("app.main.FeishuClient")
    def test_top_trending_success_sends_briefing_then_sheet_url(self, feishu_client_cls, sync_sheet) -> None:
        cfg = Config(run_report_mode="top_trending_sheet")
        report_payload = {
            "top_trending_v4": [
                GameRecord(
                    rank=1,
                    place_id=101,
                    name="Game A",
                    playing=1000,
                    fetched_at="2026-03-14T00:00:00Z",
                    created_at="2026-03-10T00:00:00Z",
                )
            ],
            "up_and_coming_v4": [],
            "top_playing_now": [],
        }
        feishu_client = MagicMock()
        feishu_client_cls.return_value = feishu_client
        sync_sheet.return_value.url = "https://feishu.cn/sheets/test"

        _notify_success(cfg, report_payload)

        feishu_client.send_group_card.assert_called_once()
        self.assertEqual(1, feishu_client.send_group_markdown.call_count)
        briefing_card = feishu_client.send_group_card.call_args.args[0]
        url_text = feishu_client.send_group_markdown.call_args.args[0]
        self.assertEqual("今日关注", briefing_card["header"]["title"]["content"])
        self.assertEqual("https://feishu.cn/sheets/test", url_text)


if __name__ == "__main__":
    unittest.main()
