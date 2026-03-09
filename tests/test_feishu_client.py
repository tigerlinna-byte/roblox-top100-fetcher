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

    def test_send_group_markdown_prefers_app_bot_for_chat_id(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        send_response = Mock()
        send_response.status_code = 200
        send_response.json.return_value = {"code": 0, "data": {"message_id": "om_test"}}

        session.request.side_effect = [auth_response, send_response]

        cfg = Config(
            feishu_app_id="cli_xxx",
            feishu_app_secret="secret",
            run_chat_id="oc_test_chat",
            feishu_bot_webhook="https://open.feishu.cn/open-apis/bot/v2/hook/test",
            request_timeout_seconds=3,
            retry_max_attempts=1,
        )
        client = FeishuClient(cfg, session=session)

        client.send_group_markdown("# Roblox\n\n- ok")

        self.assertEqual(2, session.request.call_count)

        auth_kwargs = session.request.call_args_list[0].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            auth_kwargs["url"],
        )
        self.assertEqual("cli_xxx", auth_kwargs["json"]["app_id"])

        send_kwargs = session.request.call_args_list[1].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            send_kwargs["url"],
        )
        self.assertEqual("Bearer tenant-token", send_kwargs["headers"]["Authorization"])
        self.assertEqual("oc_test_chat", send_kwargs["json"]["receive_id"])
        self.assertIn("Roblox", send_kwargs["json"]["content"]["text"])


if __name__ == "__main__":
    unittest.main()
