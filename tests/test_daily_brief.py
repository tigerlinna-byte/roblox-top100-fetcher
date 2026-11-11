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
    SpotlightSignal,
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
            long_term_signals=(SpotlightSignal("rating", 1, "新增好评 93%"), SpotlightSignal("peak_hold", 2, "处于 14 日峰值")),
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
            long_term_signals=(SpotlightSignal("rating", 1, "新增好评 91%"),),
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
            long_term_recorded_days=10,
            new_face_lookback_days=10,
        )

        text = self._market_text(spotlight)

        self.assertIn("🔥 **今日最突出 · 新面孔：<font color='blue'>Barber Simulator</font>**", text)
        self.assertIn("<font color='grey'>Simulation｜当次 CCU 4,359｜上线 28 天</font>", text)
        self.assertIn(
            "🆕 **<font color='orange'>新面孔</font>** <font color='grey'>新秀榜 #15</font>"
            "<font color='grey'>｜收入榜：未进前 300</font>",
            text,
        )
        self.assertIn("（3 款｜近 10 天没上过榜、创建 90 天内、CCU ≥3,000）", text)
        self.assertIn("其余 1 款：</font>Voxel Wars 4,070（新秀榜 #15）", text)
        self.assertEqual(1, text.count("[Rotrends](https://www.rotrends.com/game/1001)"))

        self.assertIn("🔥 **今日最突出 · 增长快：<font color='blue'>13 Days to Escape</font>**", text)
        self.assertIn(
            "📈 **<font color='red'>在线比大盘多涨 161%（较 3 天前）</font>**　"
            "💰 **<font color='purple'>新进收入榜</font>** "
            "<font color='grey'>热门榜 #16、在玩榜 #69｜上榜第 5 天｜连续第 4 天增长</font>"
            "｜收入榜 #233（一周前不在榜）",
            text,
        )
        self.assertIn("日均 CCU 12,000｜近似峰值 19,000", text)
        self.assertIn("🌱 **<font color='green'>长线 3 分</font>** <font color='grey'>新增好评 93%，处于 14 日峰值</font>", text)
        self.assertIn("🆙 **<font color='orange'>新进热门榜</font>**", text)
        self.assertIn(
            "｜收入榜 #149（较上次 <font color='green'>↓37</font>，一周 <font color='green'>↓74</font>）",
            text,
        )
        # 列表里的游戏只有长线分达标才加一行长线依据。
        self.assertNotIn("长线 1 分", text)
        self.assertIn("其余 1 款：</font>Net a Fish 16,007（新进收入榜、连续第 4 天）", text)
        self.assertIn("今天没有长线分达到门槛的其他项目。", text)

    def test_leaders_and_veterans_are_described_and_missing_history_is_stated(self) -> None:
        leader = SpotlightEntry(
            place_id=1,
            universe_id=1001,
            name="DONT SPLASH",
            genre="Runner",
            ccu=57164,
            sheet_ranks=(("在玩榜", 20), ("收入榜", 53)),
            age_days=25,
            earning=EarningMovement(rank=53, change=-4, week_change=-9, entered_this_week=False),
            leader=LeaderStatus(
                rank=20,
                rank_day_change=-2,
                rank_week_change=-8,
                ccu_day_change=-0.07,
                ccu_week_change=-0.29,
                board_streak_days=14,
                board_streak_capped=True,
                state="down",
            ),
        )
        newcomer = replace(
            leader,
            place_id=2,
            universe_id=None,
            name="No History",
            earning=None,
            leader=LeaderStatus(38, None, None, None, None, 1, False, None),
        )
        veteran = SpotlightEntry(
            place_id=3,
            name="King Legacy",
            genre="RPG",
            ccu=31123,
            sheet_ranks=(("收入榜", 31),),
            age_days=1500,
            evidence=(GrowthEvidence("earning", "收入榜 ↑181"),),
            earning=EarningMovement(rank=31, change=181, week_change=194, entered_this_week=False),
        )

        text = self._market_text(MarketSpotlight(new_game_leaders=(leader, newcomer), veteran_earners=(veteran,)))

        self.assertIn(
            "[Rotrends](https://www.rotrends.com/game/1001)：在玩榜 #20"
            "（较上次 <font color='green'>↓2</font>，一周 <font color='green'>↓8</font>）"
            "｜在线较昨天 -7%，较上周同日 -29%｜连续在榜 14 天以上｜**<font color='green'>回落</font>**"
            "｜<font color='grey'>Runner｜当次 CCU 57,164｜上线 25 天</font>｜收入榜 #53",
            text,
        )
        self.assertIn("**<font color='blue'>No History</font>**：在玩榜 #38｜<font color='grey'>Runner", text)
        self.assertIn("💰 老游戏收入异动", text)
        self.assertIn("💰 **<font color='purple'>收入榜 ↑181</font>**", text)
        self.assertIn("历史快照不可用，今天无法判断，详见下方数据异常。", text)
        self.assertIn("今天没有增长明显的新游。", text)
        self.assertNotIn("今日最突出", text)

    def test_overflow_line_is_capped_and_states_how_many_are_hidden(self) -> None:
        entry = SpotlightEntry(place_id=1, name="Game", genre="RPG", ccu=5000, sheet_ranks=(("新秀榜", 50),), age_days=10)
        overflow = tuple(replace(entry, place_id=index, name=f"Game {index}") for index in range(45))

        text = self._market_text(
            MarketSpotlight(new_face_standout=entry, new_face_overflow=overflow, new_face_lookback_days=14)
        )

        self.assertIn("其余 45 款：", text)
        self.assertIn("Game 39 5,000（新秀榜 #50）；另有 5 款未列出，见明细产物", text)
        self.assertNotIn("Game 40 ", text)

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
        self.assertIn("数据积累中（已记录 1 天）", limited_text)
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
        self.assertIn("今日最突出 · 新面孔：<font color='blue'>Big</font>", limited_text)
        self.assertIn("（1 款｜近 1 天没上过榜", limited_text)
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
