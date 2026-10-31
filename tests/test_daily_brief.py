from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.daily_brief_audience import BriefAudience, filter_brief_for_audience, resolve_brief_audiences
from app.daily_brief_card import build_daily_brief_card, strip_project_title
from app.daily_brief_models import BriefFailure, DailyBriefContent, MarketSection, ProjectBriefEntry
from app.main import (
    DailyBriefFetchPayload,
    ProjectMetricsFetchFailure,
    ProjectMetricsReportPayload,
    _notify_success,
)
from app.github_client import GitHubClientError, RepositoryFile
from app.market_pulse import MARKET_CCU_HISTORY_VAR
from app.market_spotlight import EarningMovement, MarketSpotlight, SpotlightEntry, SpotlightSignal
from app.metric_baseline import MetricAlert
from app.models import GameRecord
from app.project_metrics_sheet import PROJECT_METRICS_FIELD_TO_HEADER, PROJECT_METRICS_HEADERS
from app.project_metrics_trend import ProjectTrendSummary
from app.roblox_money_models import RobloxMoneyFetchFailure, RobloxMoneyProjectRevenue, RobloxMoneyReportPayload


FULL_CHAT = "oc_full"
LIMITED_CHAT = "oc_limited"
PRIMARY_PROJECT_ID = "9682356542"
OPEN_PROJECT_ID = "10170801715"
RESTRICTED_PROJECT_ID = "10304101434"


def _card_text(card: dict[str, object]) -> str:
    """递归收集卡片里所有文本，覆盖分栏、备注等嵌套组件。"""

    texts: list[str] = []

    def collect(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("content"), str):
                texts.append(node["content"])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(card["elements"])
    return "\n".join(texts)


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
    def test_spotlight_lines_show_earning_rank_and_changes(self) -> None:
        standout = SpotlightEntry(
            place_id=1,
            name="DONT SPLASH",
            genre="Runner",
            ccu=86967,
            sheet_ranks=(("热门榜", 1), ("收入榜", 76)),
            signals=(SpotlightSignal("earning_surge", 6, "收入榜较上次 ↑48"),),
            earning=EarningMovement(rank=76, change=48, week_change=225, entered_this_week=True),
        )
        entry = SpotlightEntry(
            place_id=2,
            name="Pixel Lineage",
            genre="RPG",
            ccu=2778,
            sheet_ranks=(("收入榜", 149),),
            signals=(SpotlightSignal("new_game", 3, "上线 25 天"),),
            earning=EarningMovement(rank=149, change=-37, week_change=-74, entered_this_week=False),
        )
        content = DailyBriefContent(
            brief_date="2026-10-30",
            market=MarketSection(
                pulse=None,
                spotlight=MarketSpotlight(standout=standout, entries=(entry,), long_term_recorded_days=3),
                genre_lines=(),
            ),
            projects=(),
            revenues=(),
            failures=(),
        )

        text = _card_text(build_daily_brief_card(Config(), content, show_revenue=False))

        self.assertIn("热门榜 #1</font>｜收入榜 #76（较上次 <font color='red'>↑48</font>，一周前不在榜）", text)
        self.assertIn(
            "｜收入榜 #149（较上次 <font color='green'>↓37</font>，一周 <font color='green'>↓74</font>）",
            text,
        )
        self.assertIn("今天没有长线分达到门槛的项目。", text)

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
        self.assertNotIn("💰 收入", text)

    def test_header_turns_orange_only_when_failures_exist(self) -> None:
        content = DailyBriefContent(brief_date="2026-10-27", market=None, projects=(), revenues=(), failures=())
        self.assertEqual("blue", build_daily_brief_card(Config(), content, show_revenue=False)["header"]["template"])

        with_failure = replace(content, failures=(BriefFailure("market", "", "行业趋势", "榜单失败"),))
        self.assertEqual(
            "orange", build_daily_brief_card(Config(), with_failure, show_revenue=False)["header"]["template"]
        )

    def test_projects_with_alerts_are_listed_first_with_marks(self) -> None:
        def trend(project_id: str, alerts: tuple[MetricAlert, ...]) -> ProjectTrendSummary:
            return ProjectTrendSummary(
                project_id=project_id,
                report_date="2026-10-26",
                summary_values=(("峰值PCU", "1,000"),),
                alerts=alerts,
                below_alert_floor=False,
            )

        fall = MetricAlert("peak_ccu", "峰值PCU", "400", 400, 1000, -0.6, "fall")
        content = DailyBriefContent(
            brief_date="2026-10-27",
            market=None,
            projects=(
                ProjectBriefEntry("1", "Steady", "", trend("1", ())),
                ProjectBriefEntry("2", "Dropping", "", trend("2", (fall,))),
            ),
            revenues=(),
            failures=(),
        )

        text = _card_text(build_daily_brief_card(Config(), content, show_revenue=False))

        self.assertLess(text.index("🟢 **Dropping**"), text.index("⚪ **Steady**"))
        self.assertIn("<font color='grey'>峰值PCU 1,000</font>", text)


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
        self.sheet_peak_ccu = "1,234"

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
                        _sheet_rows(self.sheet_peak_ccu),
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
        # 默认数据分支上还没有快照文件。
        self.github_client_cls.return_value.get_repository_file.return_value = None

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
        self.assertIn("💰 收入", full_text)
        self.assertIn("↑ 日收入（较 7 日均 +200%）", full_text)
        self.assertIn("Soccer RNG、Soccer RNG 收入", full_text)

        self.assertIn("[Troll ur friends](https://feishu.cn/sheets/10170801715)", limited_text)
        self.assertNotIn("Shoot or Shot", limited_text)
        self.assertNotIn("💰 收入", limited_text)
        self.assertNotIn("Soccer", limited_text)
        self.assertIn("数据积累中（已记录 1 天）", limited_text)

    def test_revenue_alert_is_skipped_for_project_below_peak_ccu_floor(self) -> None:
        self.sheet_peak_ccu = "50"

        _notify_success(self.cfg, self.payload)

        full_text = _card_text(self._sent_cards()[FULL_CHAT])
        self.assertIn("当日 **$114.00**", full_text)
        self.assertNotIn("日收入（较", full_text)

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
        self.github_client_cls.return_value.put_repository_file.assert_not_called()

    def test_scheduled_run_writes_game_trend_history_to_data_branch(self) -> None:
        self.github_client_cls.return_value.get_repository_file.return_value = RepositoryFile(
            content='{"version":1,"games":{"1":[["2026-10-25",40000,900,90,10]]}}',
            sha="abc",
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        put = self.github_client_cls.return_value.put_repository_file
        path, content = put.call_args.args
        self.assertEqual("game_trend_history.json", path)
        self.assertEqual("data-history", put.call_args.kwargs["branch"])
        self.assertEqual("abc", put.call_args.kwargs["sha"])
        snapshots = json.loads(content)["games"]["1"]
        self.assertEqual([["2026-10-27", 50000, 0, 0, 0], ["2026-10-25", 40000, 900, 90, 10]], snapshots)

    def test_history_read_failure_skips_write_and_still_sends_cards(self) -> None:
        self.github_client_cls.return_value.get_repository_file.side_effect = GitHubClientError("boom")

        with self.assertLogs(level="ERROR"):
            _notify_success(self.cfg, self.payload)

        self.github_client_cls.return_value.put_repository_file.assert_not_called()
        self.assertEqual({FULL_CHAT, LIMITED_CHAT}, set(self._sent_cards()))

    def test_history_write_failure_still_sends_cards(self) -> None:
        self.github_client_cls.return_value.put_repository_file.side_effect = GitHubClientError("403")

        with self.assertLogs(level="ERROR") as logs:
            _notify_success(self.cfg, self.payload)

        self.assertIn("Contents read-and-write", "\n".join(logs.output))
        self.assertEqual({FULL_CHAT, LIMITED_CHAT}, set(self._sent_cards()))

    def test_card_shows_long_term_accumulation_hint(self) -> None:
        _notify_success(self.cfg, self.payload)

        self.assertIn("还需 2 天", _card_text(self._sent_cards()[LIMITED_CHAT]))


if __name__ == "__main__":
    unittest.main()
