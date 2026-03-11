from __future__ import annotations

import json
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
        self.assertIsInstance(send_kwargs["json"]["content"], str)
        content = json.loads(send_kwargs["json"]["content"])
        self.assertIn("Roblox", content["text"])

    def test_send_group_markdown_supports_multiple_chat_ids(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        send_response_a = Mock()
        send_response_a.status_code = 200
        send_response_a.json.return_value = {"code": 0, "data": {"message_id": "om_test_a"}}

        send_response_b = Mock()
        send_response_b.status_code = 200
        send_response_b.json.return_value = {"code": 0, "data": {"message_id": "om_test_b"}}

        session.request.side_effect = [auth_response, send_response_a, send_response_b]

        cfg = Config(
            feishu_app_id="cli_xxx",
            feishu_app_secret="secret",
            run_chat_id="oc_test_chat_a, oc_test_chat_b",
            request_timeout_seconds=3,
            retry_max_attempts=1,
        )
        client = FeishuClient(cfg, session=session)

        client.send_group_markdown("Roblox sheet link")

        self.assertEqual(3, session.request.call_count)
        send_kwargs_a = session.request.call_args_list[1].kwargs
        send_kwargs_b = session.request.call_args_list[2].kwargs
        self.assertEqual("oc_test_chat_a", send_kwargs_a["json"]["receive_id"])
        self.assertEqual("oc_test_chat_b", send_kwargs_b["json"]["receive_id"])

    def test_create_spreadsheet_extracts_token_and_sheet_id(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        create_response = Mock()
        create_response.status_code = 200
        create_response.json.return_value = {
            "code": 0,
            "data": {
                "spreadsheet": {
                    "spreadsheet_token": "shtcn_sheet",
                    "url": "https://feishu.cn/sheets/shtcn_sheet",
                    "sheets": [
                        {
                            "properties": {
                                "sheet_id": "sheet001",
                            }
                        }
                    ],
                }
            },
        }

        session.request.side_effect = [auth_response, create_response]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        spreadsheet = client.create_spreadsheet("Roblox Top Trending")

        self.assertEqual("shtcn_sheet", spreadsheet.spreadsheet_token)
        self.assertEqual(("sheet001",), spreadsheet.sheet_ids)
        self.assertEqual("https://feishu.cn/sheets/shtcn_sheet", spreadsheet.url)

    def test_ensure_sheet_set_returns_three_sheet_ids(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        update_response = Mock()
        update_response.status_code = 200
        update_response.json.return_value = {
            "code": 0,
            "data": {
                "replies": [
                    {"updateSheet": {"properties": {"sheetId": "sheet001"}}},
                    {"addSheet": {"properties": {"sheetId": "sheet002"}}},
                    {"addSheet": {"properties": {"sheetId": "sheet003"}}},
                ]
            },
        }

        query_response = Mock()
        query_response.status_code = 200
        query_response.json.return_value = {
            "code": 0,
            "data": {
                "sheets": [
                    {"properties": {"sheetId": "sheet001", "title": "top_trending_v4"}},
                    {"properties": {"sheetId": "sheet002", "title": "up_and_coming_v4"}},
                    {"properties": {"sheetId": "sheet003", "title": "top_playing_now"}},
                ]
            },
        }

        session.request.side_effect = [auth_response, update_response, auth_response, query_response]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        sheet_ids = client.ensure_sheet_set(
            "shtcn_sheet",
            "sheet001",
            ["top_trending_v4", "up_and_coming_v4", "top_playing_now"],
        )

        self.assertEqual(("sheet001", "sheet002", "sheet003"), sheet_ids)

    def test_create_spreadsheet_allows_missing_default_sheet_id(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        create_response = Mock()
        create_response.status_code = 200
        create_response.json.return_value = {
            "code": 0,
            "data": {
                "spreadsheet": {
                    "spreadsheet_token": "shtcn_sheet",
                    "url": "https://feishu.cn/sheets/shtcn_sheet",
                }
            },
        }

        update_response = Mock()
        update_response.status_code = 200
        update_response.json.return_value = {
            "code": 0,
            "data": {
                "replies": [
                    {"addSheet": {"properties": {"sheetId": "sheet001"}}},
                    {"addSheet": {"properties": {"sheetId": "sheet002"}}},
                    {"addSheet": {"properties": {"sheetId": "sheet003"}}},
                ]
            },
        }

        query_response = Mock()
        query_response.status_code = 200
        query_response.json.return_value = {
            "code": 0,
            "data": {
                "sheets": [
                    {"properties": {"sheetId": "sheet001", "title": "top_trending_v4"}},
                    {"properties": {"sheetId": "sheet002", "title": "up_and_coming_v4"}},
                    {"properties": {"sheetId": "sheet003", "title": "top_playing_now"}},
                ]
            },
        }

        session.request.side_effect = [
            auth_response,
            create_response,
            auth_response,
            query_response,
            auth_response,
            update_response,
            auth_response,
            query_response,
            auth_response,
            query_response,
        ]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        spreadsheet = client.create_spreadsheet("Roblox Top Trending")
        sheet_ids = client.ensure_sheet_set(
            spreadsheet.spreadsheet_token,
            None,
            ["top_trending_v4", "up_and_coming_v4", "top_playing_now"],
        )

        self.assertEqual((), spreadsheet.sheet_ids)
        self.assertEqual(("sheet001", "sheet002", "sheet003"), sheet_ids)

    def test_write_sheet_images_posts_values_image_payload_and_row_height(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        image_response = Mock()
        image_response.status_code = 200
        image_response.content = b"png-bytes"

        write_image_response = Mock()
        write_image_response.status_code = 200
        write_image_response.json.return_value = {"code": 0, "data": {}}

        row_height_response = Mock()
        row_height_response.status_code = 200
        row_height_response.json.return_value = {"code": 0, "data": {}}

        session.request.side_effect = [
            auth_response,
            image_response,
            write_image_response,
            row_height_response,
        ]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        from app.top_trending_sheet import ThumbnailCell

        client.write_sheet_images(
            "shtcn_sheet",
            "sheet001",
            [ThumbnailCell(row_index=2, url="https://t1.example/game-a.png")],
        )

        image_fetch_kwargs = session.request.call_args_list[1].kwargs
        self.assertEqual("GET", image_fetch_kwargs["method"])
        self.assertEqual("https://t1.example/game-a.png", image_fetch_kwargs["url"])

        write_image_kwargs = session.request.call_args_list[2].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/shtcn_sheet/values_image",
            write_image_kwargs["url"],
        )
        self.assertEqual(
            "sheet001!B2:B2",
            write_image_kwargs["json"]["range"],
        )
        self.assertEqual("thumbnail_2.png", write_image_kwargs["json"]["name"])

        row_height_kwargs = session.request.call_args_list[3].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/shtcn_sheet/dimension_range",
            row_height_kwargs["url"],
        )
        self.assertEqual(
            "ROWS",
            row_height_kwargs["json"]["dimension"]["majorDimension"],
        )

    def test_apply_rank_change_colors_batches_ranges_by_color(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        style_response = Mock()
        style_response.status_code = 200
        style_response.json.return_value = {"code": 0, "data": {}}

        session.request.side_effect = [auth_response, style_response]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        from app.top_trending_sheet import RankChangeCell

        client.apply_rank_change_colors(
            "shtcn_sheet",
            "sheet001",
            [
                RankChangeCell(row_index=2, value="进榜", color="red"),
                RankChangeCell(row_index=3, value=-1, color="green"),
                RankChangeCell(row_index=4, value=0, color="black"),
            ],
        )

        style_kwargs = session.request.call_args_list[1].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/shtcn_sheet/styles_batch_update",
            style_kwargs["url"],
        )
        self.assertEqual(
            ["sheet001!E2:E2"],
            style_kwargs["json"]["data"][0]["ranges"],
        )
        self.assertEqual("#f54a45", style_kwargs["json"]["data"][0]["style"]["foreColor"])

    def test_apply_launch_date_colors_batches_ranges_by_color(self) -> None:
        session = Mock()

        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "tenant-token",
        }

        style_response = Mock()
        style_response.status_code = 200
        style_response.json.return_value = {"code": 0, "data": {}}

        session.request.side_effect = [auth_response, style_response]

        client = FeishuClient(
            Config(
                feishu_app_id="cli_xxx",
                feishu_app_secret="secret",
                request_timeout_seconds=3,
                retry_max_attempts=1,
            ),
            session=session,
        )

        from app.top_trending_sheet import LaunchDateCell

        client.apply_launch_date_colors(
            "shtcn_sheet",
            "sheet001",
            [
                LaunchDateCell(row_index=2, color="green"),
                LaunchDateCell(row_index=3, color="yellow"),
                LaunchDateCell(row_index=4, color="gray"),
            ],
        )

        style_kwargs = session.request.call_args_list[1].kwargs
        self.assertEqual(
            "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/shtcn_sheet/styles_batch_update",
            style_kwargs["url"],
        )
        self.assertEqual(
            ["sheet001!H2:H2"],
            style_kwargs["json"]["data"][0]["ranges"],
        )


if __name__ == "__main__":
    unittest.main()
