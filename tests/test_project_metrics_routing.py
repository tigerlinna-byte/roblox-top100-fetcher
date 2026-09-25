from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.config import Config
from app.feishu_client import FeishuClientError
from app.main import ProjectMetricsFetchFailure, ProjectMetricsReportPayload, _notify_success


class ProjectMetricsRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(
            run_report_mode="roblox_project_daily_metrics",
            run_chat_id="oc_full, oc_limited",
            project_metrics_primary_project_test_chat_ids="oc_full,oc_other_full",
            feishu_app_id="test_app",
            feishu_app_secret="test_secret",
            feishu_bot_webhook="https://example.com/fixed-webhook",
            roblox_creator_overview_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
            roblox_creator_overview_url_3="https://create.roblox.com/dashboard/creations/experiences/10170801715/overview",
            roblox_creator_overview_url_4="https://create.roblox.com/dashboard/creations/experiences/10304101434/overview",
            roblox_creator_overview_url_5="https://create.roblox.com/dashboard/creations/experiences/10403337696/overview",
        )
        send_patch = patch("app.main.FeishuClient.send_group_markdown", autospec=True)
        self.send = send_patch.start()
        self.addCleanup(send_patch.stop)
        sync_patch = patch("app.main._sync_project_metrics_sheet")
        self.sync = sync_patch.start()
        self.addCleanup(sync_patch.stop)
        self.sync.side_effect = lambda cfg, records, client, variables: SimpleNamespace(
            url=f"https://feishu.cn/sheets/{variables.project_id}"
        )
        self.payload = ProjectMetricsReportPayload(
            records_by_project_id={
                "9682356542": [],
                "10170801715": [],
                "10304101434": [],
                "10403337696": [],
            },
            failures=(),
        )

    def messages_by_chat(self) -> dict[str, list[str]]:
        messages: dict[str, list[str]] = {}
        for call in self.send.call_args_list:
            client, message = call.args
            for chat_id in client.config.run_chat_id.split(","):
                messages.setdefault(chat_id.strip(), []).append(message)
        return messages

    def test_scheduled_and_manual_runs_hide_soccer_links_only_in_limited_chats(self) -> None:
        for source in ("cloudflare_cron", "feishu_event"):
            for targets in ("oc_full, oc_limited", "oc_full", "oc_limited"):
                with self.subTest(source=source, targets=targets):
                    self.send.reset_mock()
                    self.sync.reset_mock()
                    _notify_success(replace(self.cfg, run_trigger_source=source, run_chat_id=targets), self.payload)
                    messages = self.messages_by_chat()
                    if "oc_full" in targets:
                        self.assertEqual(
                            [f"https://feishu.cn/sheets/{project_id}" for project_id in self.payload.records_by_project_id],
                            messages["oc_full"],
                        )
                    if "oc_limited" in targets:
                        self.assertEqual(["https://feishu.cn/sheets/10170801715"], messages["oc_limited"])
                    self.assertNotIn("oc_other_full", messages)
                    self.assertEqual(4, self.sync.call_count)

    def test_project_ids_control_visibility_even_when_configuration_slots_change(self) -> None:
        cfg = replace(
            self.cfg,
            roblox_creator_overview_url_3=self.cfg.roblox_creator_overview_url_4,
            roblox_creator_overview_url_4=self.cfg.roblox_creator_overview_url_3,
        )
        _notify_success(cfg, self.payload)
        self.assertEqual(["https://feishu.cn/sheets/10170801715"], self.messages_by_chat()["oc_limited"])

    def failure_payload(self, project_ids: tuple[str, ...]) -> ProjectMetricsReportPayload:
        return ProjectMetricsReportPayload(
            records_by_project_id={},
            failures=tuple(
                ProjectMetricsFetchFailure(project_id, f"https://example.com/{project_id}", f"private-detail-{project_id}")
                for project_id in project_ids
            ),
        )

    def test_failure_summaries_are_filtered_and_recounted_for_each_audience(self) -> None:
        payload = self.failure_payload(("10170801715", "10304101434", "10403337696"))
        _notify_success(self.cfg, payload)
        messages = self.messages_by_chat()
        self.assertEqual(1, len(messages["oc_full"]))
        self.assertIn("失败项目数: 3", messages["oc_full"][0])
        for failure in payload.failures:
            self.assertIn(failure.reason, messages["oc_full"][0])
        self.assertEqual(1, len(messages["oc_limited"]))
        self.assertIn("失败项目数: 1", messages["oc_limited"][0])
        self.assertIn("private-detail-10170801715", messages["oc_limited"][0])
        self.assertNotIn("10304101434", messages["oc_limited"][0])
        self.assertNotIn("10403337696", messages["oc_limited"][0])
        self.sync.assert_not_called()

    def test_soccer_only_failures_do_not_send_empty_summary_to_limited_group(self) -> None:
        for targets in ("oc_full,oc_limited", "oc_limited"):
            with self.subTest(targets=targets):
                self.send.reset_mock()
                _notify_success(
                    replace(self.cfg, run_chat_id=targets),
                    self.failure_payload(("10304101434", "10403337696")),
                )
                messages = self.messages_by_chat()
                self.assertNotIn("oc_limited", messages)
                self.assertEqual({"oc_full"} if "oc_full" in targets else set(), set(messages))

    def test_missing_recipient_configuration_fails_before_any_notification(self) -> None:
        for overrides, expected_error in (
            ({"project_metrics_primary_project_test_chat_ids": "  , "}, "PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS"),
            ({"run_chat_id": ""}, "RUN_CHAT_ID"),
            ({"feishu_app_id": ""}, "FEISHU_APP_ID"),
            ({"feishu_app_secret": ""}, "FEISHU_APP_SECRET"),
        ):
            for payload in (self.payload, self.failure_payload(("10304101434", "10403337696"))):
                with self.subTest(overrides=overrides, has_failures=bool(payload.failures)):
                    with self.assertRaisesRegex(FeishuClientError, expected_error):
                        _notify_success(replace(self.cfg, **overrides), payload)
                    self.send.assert_not_called()
                    self.sync.assert_not_called()

    def test_restricted_notifications_cannot_fall_back_to_fixed_webhook(self) -> None:
        _notify_success(self.cfg, self.payload)
        for call in self.send.call_args_list:
            client, message = call.args
            if "10304101434" in message or "10403337696" in message:
                self.assertEqual("oc_full", client.config.run_chat_id)
                self.assertEqual("", client.config.feishu_bot_webhook)


if __name__ == "__main__":
    unittest.main()
