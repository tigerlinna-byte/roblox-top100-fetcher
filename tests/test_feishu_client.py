from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.config import Config
from app.feishu_client import FeishuClient


class FeishuClientTests(unittest.TestCase):
    def test_send_group_markdown_uses_webhook_payload(self) -> None:
        session = Mock()
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"StatusCode": 0}
        session.request.return_value = response

        cfg = Config(
            feishu_bot_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            request_timeout_seconds=3,
            retry_max_attempts=1,
        )
        client = FeishuClient(cfg, session=session)

        client.send_group_markdown("# Roblox\n\n- ok")

        session.request.assert_called_once()
        kwargs = session.request.call_args.kwargs
        self.assertEqual("POST", kwargs["method"])
        self.assertEqual(cfg.feishu_bot_webhook, kwargs["url"])
        self.assertEqual("text", kwargs["json"]["msg_type"])
        self.assertIn("Roblox", kwargs["json"]["content"]["text"])


if __name__ == "__main__":
    unittest.main()
