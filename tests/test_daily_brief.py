from __future__ import annotations

import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.daily_brief_audience import BriefAudience, filter_brief_for_audience, resolve_brief_audiences
from app.daily_brief_card import build_daily_brief_card, strip_project_title
from app.daily_brief_models import BriefFailure, DailyBriefContent, ProjectBriefEntry
from app.main import (
    DailyBriefFetchPayload,
    ProjectMetricsFetchFailure,
    ProjectMetricsReportPayload,
    _notify_success,
)
from app.market_pulse import MARKET_CCU_HISTORY_VAR
from app.models import GameRecord
from app.project_metrics_sheet import PROJECT_METRICS_FIELD_TO_HEADER, PROJECT_METRICS_HEADERS
from app.roblox_money_models import RobloxMoneyFetchFailure, RobloxMoneyProjectRevenue, RobloxMoneyReportPayload


FULL_CHAT = "oc_full"
LIMITED_CHAT = "oc_limited"
PRIMARY_PROJECT_ID = "9682356542"
OPEN_PROJECT_ID = "10170801715"
RESTRICTED_PROJECT_ID = "10304101434"


def _card_text(card: dict[str, object]) -> str:
    return "\n".join(str(element.get("content", "")) for element in card["elements"])


def _sheet_rows(peak_ccu: str) -> list[list[str]]:
    rows = [PROJECT_METRICS_HEADERS.copy()]
    row = [""] * len(PROJECT_METRICS_HEADERS)
    row[0] = "2026-10-26"
    row[PROJECT_METRICS_HEADERS.index(PROJECT_METRICS_FIELD_TO_HEADER["peak_ccu"])] = peak_ccu
    rows.append(row)
    return rows


class DailyBriefAudienceTests(unittest.TestCase):
    def test_audiences_split_full_and_limited_chats(self) -> None:
        audiences = resolve_brief_audiences((FULL_CHAT, LIMITED_CHAT), (FULL_CHAT, "oc_other"))

        self.assertEqual(
            (
                BriefAudience(chat_ids=(FULL_CHAT,), is_full_group=True),
                BriefAudience(chat_ids=(LIMITED_CHAT,), is_full_group=False),
            ),
            audiences,
        )

    def test_missing_full_group_config_treats_all_chats_as_limited(self) -> None:
        self.assertEqual(
            (BriefAudience(chat_ids=(FULL_CHAT,), is_full_group=False),),
            resolve_brief_audiences((FULL_CHAT,), ()),
        )

    def test_limited_audience_hides_restricted_projects_revenue_and_their_failures(self) -> None:
        content = DailyBriefContent(
            brief_date="2026-10-27",
            market=None,
            projects=(
                ProjectBriefEntry(OPEN_PROJECT_ID, "Troll", "", None),
                ProjectBriefEntry(RESTRICTED_PROJECT_ID, "Soccer", "", None),
            ),
            revenues=(),
            failures=(
                BriefFailure("market", "", "行业趋势", "榜单失败"),
                BriefFailure("project", OPEN_PROJECT_ID, "Troll", "可见失败"),
                BriefFailure("project", RESTRICTED_PROJECT_ID, "Soccer", "受限失败"),
                BriefFailure("money", OPEN_PROJECT_ID, "Troll 收入", "收入失败"),
            ),
        )

        filtered = filter_brief_for_audience(
            content,
            BriefAudience(chat_ids=(LIMITED_CHAT,), is_full_group=False),
            frozenset({RESTRICTED_PROJECT_ID}),
        )

        self.assertEqual([OPEN_PROJECT_ID], [entry.project_id for entry in filtered.projects])
        self.assertEqual(["榜单失败", "可见失败"], [failure.reason for failure in filtered.failures])


class DailyBriefCardTests(unittest.TestCase):
    def test_strip_project_title_removes_sheet_suffix(self) -> None:
        self.assertEqual("Shoot or Shot", strip_project_title("Shoot or Shot 每日数据"))
        self.assertEqual("Troll ur friends", strip_project_title("Troll ur friends"))

    def test_failures_with_same_reason_are_merged(self) -> None:
        content = DailyBriefContent(
            brief_date="2026-10-27",
            market=None,
            projects=(),
            revenues=(),
            failures=(
                BriefFailure("project", "1", "A", "Cookie 失效"),
                BriefFailure("project", "2", "B", "Cookie 失效"),
            ),
        )

        text = _card_text(build_daily_brief_card(Config(), content, show_revenue=False))

        self.assertIn("A、B</font>：Cookie 失效", text)
        self.assertNotIn("**收入**", text)


class DailyBriefFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(
            run_report_mode="daily_brief",
            run_trigger_source="cloudflare_cron",
            run_chat_id=f"{FULL_CHAT},{LIMITED_CHAT}",
            project_metrics_primary_project_test_chat_ids=FULL_CHAT,
            feishu_app_id="app",
            feishu_app_secret="secret",
            feishu_bot_webhook="https://example.com/webhook",
            roblox_creator_overview_url=f"https://create.roblox.com/dashboard/creations/experiences/{PRIMARY_PROJECT_ID}/overview",
            roblox_creator_overview_url_3=f"https://create.roblox.com/dashboard/creations/experiences/{OPEN_PROJECT_ID}/overview",
            roblox_creator_overview_url_4=f"https://create.roblox.com/dashboard/creations/experiences/{RESTRICTED_PROJECT_ID}/overview",
            feishu_project_metrics_spreadsheet_title="Shoot or Shot 每日数据",
        )
        self.payload = DailyBriefFetchPayload(
            records_by_sheet={
                "top_playing_now": [
                    GameRecord(rank=1, place_id=1, name="Big", playing=50000, fetched_at="2026-10-27T01:00:00Z"),
                ],
            },
            market_failure="",
            project_metrics=ProjectMetricsReportPayload(
                records_by_project_id={PRIMARY_PROJECT_ID: [], OPEN_PROJECT_ID: []},
                failures=(ProjectMetricsFetchFailure(RESTRICTED_PROJECT_ID, "", "Roblox 登录 Cookie 已失效"),),
            ),
            project_failure="",
            money=RobloxMoneyReportPayload(
                project_revenues=(
                    RobloxMoneyProjectRevenue(
                        project_id=OPEN_PROJECT_ID,
                        project_name="Troll ur friends",
                        source_url="",
                        revenue_metric="Revenue",
                        report_date="2026-10-25",
                        month_start_date="2026-10-01",
                        month_end_date="2026-10-25",
                        daily_robux=30000,
                        month_to_date_robux=300000,
                        usd_per_100k_robux=380,
                        fetched_at="",
                        baseline_daily_robux=(10000, 10000, 10000, 10000),
                    ),
                ),
                failures=(RobloxMoneyFetchFailure(RESTRICTED_PROJECT_ID, "Soccer RNG", "", "Roblox 登录 Cookie 已失效"),),
            ),
            money_failure="",
        )
        self.clients: list[MagicMock] = []

        def build_client(cfg: Config) -> MagicMock:
            client = MagicMock()
            client.config = cfg
            self.clients.append(client)
            return client

        for target, kwargs in (
            ("app.main.FeishuClient", {"side_effect": build_client}),
            (
                "app.main._sync_project_metrics_sheet_rows",
                {
                    "side_effect": lambda cfg, records, client, variables: (
                        SimpleNamespace(url=f"https://feishu.cn/sheets/{variables.project_id}"),
                        _sheet_rows("1,234"),
                    )
                },
            ),
            ("app.main._persist_top_trending_previous_ranks", {}),
            ("app.main.write_json_document", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        github_patcher = patch("app.main.GitHubClient")
        self.github_client_cls = github_patcher.start()
        self.addCleanup(github_patcher.stop)

    def _sent_cards(self) -> dict[str, dict[str, object]]:
        return {
            client.config.run_chat_id: client.send_group_card.call_args.args[0]
            for client in self.clients
            if client.send_group_card.called
        }

    def test_each_audience_gets_its_own_card(self) -> None:
        _notify_success(self.cfg, self.payload)

        cards = self._sent_cards()
        self.assertEqual({FULL_CHAT, LIMITED_CHAT}, set(cards))
        full_text = _card_text(cards[FULL_CHAT])
        limited_text = _card_text(cards[LIMITED_CHAT])

        self.assertIn("[Shoot or Shot](https://feishu.cn/sheets/9682356542)", full_text)
        self.assertIn("**收入**", full_text)
        self.assertIn("↑ 日收入（较 7 日均 +200%）", full_text)
        self.assertIn("Soccer RNG、Soccer RNG 收入", full_text)

        self.assertIn("[Troll ur friends](https://feishu.cn/sheets/10170801715)", limited_text)
        self.assertNotIn("Shoot or Shot", limited_text)
        self.assertNotIn("**收入**", limited_text)
        self.assertNotIn("Soccer", limited_text)
        self.assertIn("数据积累中（已记录 1 天）", limited_text)

    def test_full_group_send_never_falls_back_to_webhook(self) -> None:
        _notify_success(self.cfg, self.payload)

        full_client = next(client for client in self.clients if client.config.run_chat_id == FULL_CHAT)
        self.assertEqual("", full_client.config.feishu_bot_webhook)

    def test_scheduled_run_persists_market_history(self) -> None:
        _notify_success(self.cfg, self.payload)

        upsert = self.github_client_cls.return_value.upsert_repository_variable
        name, value = upsert.call_args.args
        self.assertEqual(MARKET_CCU_HISTORY_VAR, name)
        self.assertEqual(50000, json.loads(value)["history"][0]["broad_ccu"])

    def test_manual_run_does_not_persist_market_history(self) -> None:
        cfg = Config(**{**self.cfg.__dict__, "run_trigger_source": "feishu_command"})

        _notify_success(cfg, self.payload)

        self.github_client_cls.return_value.upsert_repository_variable.assert_not_called()


if __name__ == "__main__":
    unittest.main()
