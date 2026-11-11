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
from app.market_spotlight import (
    EarningMovement,
    GrowthEvidence,
    LeaderStatus,
    MarketSpotlight,
    SpotlightEntry,
    RetentionVerdict,
)
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
    def _market_text(self, spotlight: MarketSpotlight) -> str:
        content = DailyBriefContent(
            brief_date="2026-11-11",
            market=MarketSection(pulse=None, spotlight=spotlight, genre_lines=()),
            projects=(),
            revenues=(),
            failures=(),
        )
        return _card_text(build_daily_brief_card(Config(), content, show_revenue=False))

    def test_new_face_and_growth_sections_show_badges_ranks_and_earning(self) -> None:
        new_face = SpotlightEntry(
            place_id=1,
            universe_id=1001,
            name="Barber Simulator",
            genre="Simulation",
            ccu=4359,
            sheet_ranks=(("新秀榜", 15),),
            age_days=28,
            days_on_board=1,
        )
        growing = SpotlightEntry(
            place_id=2,
            name="13 Days to Escape",
            genre="Escape",
            ccu=16007,
            sheet_ranks=(("热门榜", 16), ("在玩榜", 69), ("收入榜", 233)),
            age_days=32,
            evidence=(
                GrowthEvidence("ccu", "在线比大盘多涨 161%（较 3 天前）"),
                GrowthEvidence("earning", "新进收入榜"),
            ),
            retention=RetentionVerdict("watch", 15.2, None, 0.95, 0.93),
            earning=EarningMovement(rank=233, change=None, week_change=68, entered_this_week=True),
            average_ccu=12000,
            peak_ccu=19000,
            ccu_sample_count=4,
            days_on_board=5,
            growth_streak_days=4,
        )
        listed_growth = replace(
            growing,
            place_id=3,
            name="Pixel Lineage",
            evidence=(GrowthEvidence("board_entry", "新进热门榜"),),
            retention=RetentionVerdict("bad", 6.4, None, 0.85, 0.689),
            earning=EarningMovement(rank=149, change=-37, week_change=-74, entered_this_week=False),
            growth_streak_days=1,
        )
        spotlight = MarketSpotlight(
            new_face_standout=new_face,
            new_faces=(replace(new_face, place_id=4, name="Skate Tree", universe_id=None),),
            new_face_overflow=(replace(new_face, place_id=5, name="Voxel Wars", ccu=4070),),
            growth_standout=growing,
            growth=(listed_growth,),
            growth_overflow=(replace(growing, place_id=6, name="Net a Fish", evidence=growing.evidence[1:]),),
            long_term=(
                replace(
                    new_face,
                    place_id=7,
                    universe_id=1007,
                    name="Gun Forge",
                    retention=RetentionVerdict("good", 33.0, None, 1.04, 0.92),
                ),
            ),
            long_term_recorded_days=10,
            new_face_lookback_days=10,
        )

        text = self._market_text(spotlight)

        self.assertIn("🔥 <font color='grey'>今日最突出 · 新面孔：</font>**<font color='blue'>Barber Simulator</font>**", text)
        # 新面孔只占一行：品类、CCU、上线天数和出现的榜单；栏目已说明是新面孔，不再重复，没进收入榜就不写收入榜。
        self.assertIn("<font color='grey'>Simulation｜当次 CCU 4,359｜上线 28 天｜新秀榜 #15</font>", text)
        self.assertIn(
            "- **<font color='blue'>Skate Tree</font>** <font color='grey'>Simulation｜当次 CCU 4,359｜上线 28 天｜新秀榜 #15</font>\n",
            text,
        )
        self.assertNotIn("新面孔</font> ", text)
        self.assertNotIn("未进前", text)
        self.assertIn("（共 3 款，展示前 2 款｜近 10 天没上过榜、创建 90 天内、CCU ≥3,000）", text)
        self.assertEqual(1, text.count("[Rotrends](https://www.rotrends.com/game/1001)"))
        # 排名靠后的游戏不在卡片上列出，只体现在总数里。
        self.assertNotIn("Voxel Wars", text)
        self.assertNotIn("其余", text)

        self.assertIn("🔥 <font color='grey'>今日最突出 · 增长快：</font>**<font color='blue'>13 Days to Escape</font>**", text)
        self.assertIn(
            "<font color='red-400'>在线比大盘多涨 161%（较 3 天前）</font>　"
            "<font color='purple-400'>新进收入榜</font>"
            "<font color='grey'>｜连续第 4 天增长</font>"
            "｜收入榜 #233（一周前不在榜）",
            text,
        )
        # 不再列三个榜单的名次、上榜天数和近似峰值。
        self.assertIn("<font color='grey'>Escape｜日均 CCU 12,000｜上线 32 天</font>", text)
        for removed in ("近似峰值", "上榜第", "热门榜 #16"):
            self.assertNotIn(removed, text)
        # 今日最突出总是写出留存结论；好评率正常时不写。
        self.assertIn("<font color='grey'>◐ 待观察</font>｜单局约 15 分钟 · 在线守住 14 日峰值的 95%", text)
        self.assertIn("<font color='grey'>留存数据积累中</font>", text)
        self.assertIn("　<font color='orange-400'>新进热门榜</font>", text)
        # 列表里只有留不住的才加一行，偏低的好评作为警告写出。
        self.assertIn(
            "　<font color='red-400'>○ 留不住</font>｜单局约 6 分钟 · 在线守住 14 日峰值的 85% · 好评仅 68%", text
        )
        # 长线潜力栏：结论加两项关键数据，守住峰值超过 100% 时按 100% 写。
        self.assertIn(
            "**<font color='blue'>Gun Forge</font>** [Rotrends](https://www.rotrends.com/game/1007)："
            "<font color='green-400'>● 留得住</font>｜单局约 33 分钟 · 在线守住 14 日峰值的 100%",
            text,
        )
        self.assertNotIn("好评 92%", text)
        # 条目里不再有彩色表情，栏目标题的表情保留。
        for emoji in ("🆙", "💰", "🔺", "🔻", "✨", "🍂", "⚠️"):
            self.assertNotIn(emoji, text)
        self.assertIn("🌱 长线潜力", text)
        self.assertIn(
            "｜收入榜 #149（较上次 <font color='green'>↓37</font>，一周 <font color='green'>↓74</font>）",
            text,
        )
        # 游戏名是唯一加粗的彩色文字，标识不加粗。
        self.assertNotIn("**<font color='orange", text)
        self.assertNotIn("**<font color='red", text)
        self.assertIn("（共 3 款，展示前 2 款｜创建 90 天内、CCU ≥3,000）", text)
        self.assertNotIn("Net a Fish", text)

    def test_earning_change_is_not_repeated_after_earning_evidence(self) -> None:
        entry = SpotlightEntry(
            place_id=1,
            name="Impossible Hill Climb",
            genre="Incremental Simulator",
            ccu=4803,
            sheet_ranks=(("新秀榜", 36), ("收入榜", 231)),
            age_days=17,
            evidence=(GrowthEvidence("earning", "收入榜 ↑66"),),
            earning=EarningMovement(rank=231, change=66, week_change=70, entered_this_week=True),
        )

        text = self._market_text(MarketSpotlight(growth_standout=entry))

        self.assertIn("<font color='purple-400'>收入榜 ↑66</font>｜收入榜 #231（一周前不在榜）", text)
        self.assertEqual(1, text.count("↑66"))

    def test_manual_run_before_scheduled_brief_points_to_scheduled_brief(self) -> None:
        entry = SpotlightEntry(
            place_id=1,
            name="Throw Food",
            genre="Tycoon",
            ccu=132831,
            sheet_ranks=(("在玩榜", 6),),
            age_days=54,
            leader=LeaderStatus(rank=6, ccu=132831, ccu_week_ago=None, week_change=None, state=None),
        )

        text = self._market_text(
            MarketSpotlight(
                growth_standout=replace(entry, evidence=(GrowthEvidence("board_entry", "新进热门榜"),)),
                new_game_leaders=(entry,),
                long_term_recorded_days=10,
                new_face_lookback_days=10,
                before_scheduled_snapshot=True,
            )
        )

        self.assertIn("<font color='grey'>留存：手动运行早于今天的定时早报，以定时早报为准</font>", text)
        self.assertIn("<font color='grey'>在线 13.3 万｜手动运行早于今天的定时早报，以定时早报为准</font>", text)
        self.assertIn("<font color='grey'>手动运行早于今天的定时早报，以定时早报为准。</font>", text)
        self.assertNotIn("缺少上周同日数据", text)
        self.assertNotIn("留存数据积累中", text)

    def test_section_count_omits_shown_note_when_everything_is_listed(self) -> None:
        entry = SpotlightEntry(place_id=1, name="Game", genre="RPG", ccu=5000, sheet_ranks=(("新秀榜", 50),), age_days=10)

        text = self._market_text(
            MarketSpotlight(
                new_face_standout=replace(entry, retention=RetentionVerdict("watch", None, "missing", 0.9, 0.9)),
                new_faces=(replace(entry, place_id=2),),
                growth_standout=replace(
                    entry, place_id=3, name="Idle", retention=RetentionVerdict("watch", None, "afk", 0.82, 0.95)
                ),
                new_face_lookback_days=14,
                long_term_recorded_days=5,
            )
        )

        self.assertIn("（共 2 款｜近 14 天没上过榜", text)
        self.assertIn("（共 1 款｜创建 90 天内", text)
        self.assertIn("<font color='grey'>◐ 待观察</font>｜单局时长暂无（采样不足） · 在线守住 14 日峰值的 90%", text)
        self.assertIn("<font color='grey'>◐ 待观察</font>｜疑似挂机，单局时长不参与判断 · 在线守住 14 日峰值的 82%", text)
        self.assertIn("今天没有其他留得住的新游。", text)
        self.assertNotIn("展示前", text)

    def test_leader_trend_lines_show_conclusion_and_week_ccu(self) -> None:
        base = SpotlightEntry(
            place_id=1,
            universe_id=1001,
            name="Throw Food For Animals",
            genre="Tycoon",
            ccu=194900,
            sheet_ranks=(("在玩榜", 6), ("收入榜", 10)),
            age_days=54,
            earning=EarningMovement(rank=10, change=2, week_change=28, entered_this_week=False),
            leader=LeaderStatus(rank=6, ccu=194900, ccu_week_ago=77000, week_change=1.531, state="up"),
        )
        falling = replace(
            base,
            place_id=2,
            universe_id=None,
            name="DONT SPLASH",
            leader=LeaderStatus(rank=20, ccu=57164, ccu_week_ago=80500, week_change=-0.29, state="down"),
        )
        steady = replace(
            base,
            place_id=3,
            universe_id=None,
            name="Steady",
            leader=LeaderStatus(rank=25, ccu=9500, ccu_week_ago=9000, week_change=0.056, state="flat"),
        )
        newcomer = replace(
            base,
            place_id=4,
            universe_id=None,
            name="Bloody Ragdoll",
            leader=LeaderStatus(rank=30, ccu=29050, ccu_week_ago=None, week_change=None, state="new"),
        )
        unknown = replace(
            base,
            place_id=5,
            universe_id=None,
            name="No History",
            leader=LeaderStatus(rank=38, ccu=12000, ccu_week_ago=None, week_change=None, state=None),
        )

        text = self._market_text(MarketSpotlight(new_game_leaders=(base, falling, steady, newcomer, unknown)))

        self.assertIn("👑 头部新游趋势** <font color='grey'>（在玩榜排名最高的新游，在线较上周同日）</font>", text)
        self.assertIn(
            "**<font color='blue'>Throw Food For Animals</font>** [Rotrends](https://www.rotrends.com/game/1001)："
            "<font color='red-400'>▲ 上升</font>｜在线 7.7 万 → 19.5 万（较上周同日 +153%）",
            text,
        )
        self.assertIn("：<font color='green-400'>▼ 回落</font>｜在线 8.1 万 → 5.7 万（较上周同日 -29%）", text)
        self.assertIn("：<font color='grey'>– 平稳</font>｜在线 9,000 → 9,500（较上周同日 +6%）", text)
        self.assertIn("：<font color='orange-400'>＋ 新晋</font>｜在线 2.9 万（一周前未上榜）", text)
        self.assertIn("：<font color='grey'>在线 1.2 万｜缺少上周同日数据，今天不判断</font>", text)
        # 每行只有结论和在线人数，不再列品类、上线天数、收入榜、连续在榜等。
        self.assertNotIn("Tycoon", text)
        self.assertNotIn("收入榜 #10", text)
        self.assertNotIn("连续在榜", text)

    def test_missing_history_is_stated(self) -> None:
        text = self._market_text(MarketSpotlight())

        self.assertIn("历史快照不可用，今天无法判断，详见下方数据异常。", text)
        self.assertIn("今天没有增长明显的新游。", text)
        self.assertNotIn("今日最突出", text)
        self.assertNotIn("老游戏", text)

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
                    GameRecord(
                        rank=1,
                        place_id=1,
                        name="Big",
                        playing=50000,
                        fetched_at="2026-10-27T01:00:00Z",
                        created_at="2026-10-20T00:00:00Z",
                    ),
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
        self.assertIn(
            "**大盘暂不判断**<font color='grey'>（缺少上周同日数据）</font>｜在玩榜前 100 合计 5.0 万"
            "<font color='grey'>（数据积累中，已记录 1 天）</font>",
            limited_text,
        )
        self.assertIn("触发：定时", limited_text)
        # 统计日期写在栏目标题里，项目行和收入行不再重复。
        self.assertIn("🎮 自家项目（2026-10-26）", limited_text)
        self.assertIn("峰值PCU 1,234｜D1 待出｜时长 待出", limited_text)
        self.assertIn("💰 收入（截至 2026-10-25）", full_text)
        self.assertNotIn("（截至 2026-10-25）：", full_text)
        # 数据分支上还没有快照：如实说明当天没有判断，而不是把所有游戏都当成新面孔。
        for card_text in (full_text, limited_text):
            self.assertIn("值得关注</font>：还没有可用的历史快照，今天不判断新面孔和在线涨幅", card_text)
            self.assertIn("历史快照不可用，今天无法判断，详见下方数据异常。", card_text)

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

    def _use_data_branch_files(self, **files: str) -> None:
        """按文件名返回数据分支上的内容，键去掉 .json 后缀；未列出的文件视为不存在。"""

        self.github_client_cls.return_value.get_repository_file.side_effect = lambda path, *, branch: (
            RepositoryFile(content=files[path.removesuffix(".json")], sha=f"sha-{path}")
            if path.removesuffix(".json") in files
            else None
        )

    def _written_files(self) -> dict[str, tuple[str, str]]:
        """本次写入数据分支的文件：文件名 -> (内容, 基于的 sha)。"""

        put = self.github_client_cls.return_value.put_repository_file
        return {call.args[0]: (call.args[1], call.kwargs["sha"]) for call in put.call_args_list}

    def test_scheduled_run_writes_game_trend_history_to_data_branch(self) -> None:
        self._use_data_branch_files(game_trend_history='{"version":1,"games":{"1":[["2026-10-25",40000,900,90,10]]}}')

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        put = self.github_client_cls.return_value.put_repository_file
        self.assertEqual("data-history", put.call_args.kwargs["branch"])
        content, sha = self._written_files()["game_trend_history.json"]
        self.assertEqual("sha-game_trend_history.json", sha)
        snapshots = json.loads(content)["games"]["1"]
        self.assertEqual([["2026-10-27", 50000, 0, 0, 0], ["2026-10-25", 40000, 900, 90, 10]], snapshots)

    def test_scheduled_run_records_new_faces_in_hit_history(self) -> None:
        self._use_data_branch_files(
            # 另一款游戏昨天有快照，说明历史可用；榜单上的游戏此前没出现过，是新面孔。
            game_trend_history='{"version":1,"games":{"2":[["2026-10-26",40000,900,90,10]]}}',
            spotlight_hit_history='{"version":1,"days":{"2026-10-26":{"new_face":[7],"growth":[8]}}}',
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        content, sha = self._written_files()["spotlight_hit_history.json"]
        self.assertEqual("sha-spotlight_hit_history.json", sha)
        self.assertEqual(
            {
                "2026-10-27": {"new_face": [1], "growth": []},
                "2026-10-26": {"new_face": [7], "growth": [8]},
            },
            json.loads(content)["days"],
        )
        limited_text = _card_text(self._sent_cards()[LIMITED_CHAT])
        self.assertIn("今日最突出 · 新面孔：</font>**<font color='blue'>Big</font>**", limited_text)
        self.assertIn("（共 1 款｜近 1 天没上过榜", limited_text)
        self.assertNotIn("还没有可用的历史快照", limited_text)

    def test_scheduled_run_applies_previous_samples_and_opens_next_window(self) -> None:
        self._use_data_branch_files(
            game_ccu_samples=(
                '{"version":1,"window_date":"2026-10-26","universes":{"100":1},'
                '"sampled_at":["t1","t2","t3"],"games":{"1":[10000,20000,30000]}}'
            )
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        written = self._written_files()
        snapshot = json.loads(written["game_trend_history.json"][0])["games"]["1"][0]
        # 3 次定时采样加早报自身 50000：均值 27500，近似峰值 50000，共 4 次。
        self.assertEqual(["2026-10-27", 50000, 0, 0, 0, 27500, 50000, 4], snapshot)
        window_content, window_sha = written["game_ccu_samples.json"]
        window = json.loads(window_content)
        self.assertEqual("sha-game_ccu_samples.json", window_sha)
        self.assertEqual("2026-10-27", window["window_date"])
        self.assertEqual([], window["sampled_at"])
        self.assertEqual({}, window["games"])
        self.assertNotIn("CCU 采样", _card_text(self._sent_cards()[LIMITED_CHAT]))

    def test_too_few_samples_are_reported_to_both_audiences(self) -> None:
        self._use_data_branch_files(
            game_ccu_samples=(
                '{"version":1,"window_date":"2026-10-26","universes":{"100":1},'
                '"sampled_at":["t1"],"games":{"1":[10000]}}'
            )
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        snapshot = json.loads(self._written_files()["game_trend_history.json"][0])["games"]["1"][0]
        self.assertEqual(["2026-10-27", 50000, 0, 0, 0], snapshot)
        for card in self._sent_cards().values():
            self.assertIn("CCU 采样 2/4 次，时长暂不计分", _card_text(card))

    def test_rerun_on_same_day_keeps_samples_of_the_open_window(self) -> None:
        self._use_data_branch_files(
            game_ccu_samples=(
                '{"version":1,"window_date":"2026-10-27","universes":{"100":1},'
                '"sampled_at":["t1"],"games":{"1":[10000]}}'
            )
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(self.cfg, self.payload)

        self.assertNotIn("game_ccu_samples.json", self._written_files())
        self.assertNotIn("CCU 采样", _card_text(self._sent_cards()[LIMITED_CHAT]))

    def test_manual_run_uses_samples_without_resetting_window(self) -> None:
        cfg = Config(**{**self.cfg.__dict__, "run_trigger_source": "feishu_command"})
        self._use_data_branch_files(
            game_ccu_samples=(
                '{"version":1,"window_date":"2026-10-26","universes":{"100":1},'
                '"sampled_at":["t1"],"games":{"1":[10000]}}'
            )
        )

        with patch("app.main.resolve_local_today", return_value=date(2026, 10, 27)):
            _notify_success(cfg, self.payload)

        self.github_client_cls.return_value.put_repository_file.assert_not_called()

    def test_samples_read_failure_is_reported(self) -> None:
        def get_file(path: str, *, branch: str) -> None:
            if path == "game_ccu_samples.json":
                raise GitHubClientError("boom")

        self.github_client_cls.return_value.get_repository_file.side_effect = get_file

        with self.assertLogs(level="ERROR"):
            _notify_success(self.cfg, self.payload)

        self.assertNotIn("game_ccu_samples.json", self._written_files())
        self.assertIn("读取采样数据失败，时长暂不计分", _card_text(self._sent_cards()[LIMITED_CHAT]))

    def test_history_read_failure_skips_write_and_still_sends_cards(self) -> None:
        self.github_client_cls.return_value.get_repository_file.side_effect = GitHubClientError("boom")

        with self.assertLogs(level="ERROR"):
            _notify_success(self.cfg, self.payload)

        self.github_client_cls.return_value.put_repository_file.assert_not_called()
        self.assertEqual({FULL_CHAT, LIMITED_CHAT}, set(self._sent_cards()))
        for card in self._sent_cards().values():
            card_text = _card_text(card)
            self.assertIn("游戏每日快照读取失败，今天不判断新面孔、在线涨幅和长线潜力", card_text)
            self.assertIn("命中历史读取失败，今天不标注连续增长天数", card_text)

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
