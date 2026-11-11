"""把早报内容组装成飞书卡片。"""

from __future__ import annotations

from .config import SCHEDULED_TRIGGER_SOURCE, Config
from .daily_brief_models import DailyBriefContent, MarketSection, ProjectBriefEntry, RevenueBriefEntry
from .daily_brief_rules import (
    LONG_TERM_MIN_RECORDED_DAYS,
    LONG_TERM_PEAK_WINDOW_DAYS,
    MARKET_PULSE_BROAD_SIZE,
    NEW_FACE_LOOKBACK_DAYS,
    PROJECT_TITLE_SUFFIXES_TO_STRIP,
    PROJECT_TREND_BASELINE_DAYS,
    RETENTION_BAD_LIKE_RATIO,
    SPOTLIGHT_MAX_GAME_AGE_DAYS,
    SPOTLIGHT_MIN_CCU,
)
from .market_pulse import MarketPulse, MarketTrend
from .market_spotlight import (
    TOP_EARNING_SHEET_KEY,
    EvidenceKind,
    LeaderState,
    LeaderStatus,
    MarketSpotlight,
    RetentionTier,
    RetentionVerdict,
    SpotlightEntry,
)
from .metric_baseline import MetricAlert
from .roblox_money_summary import format_robux, format_usd
from .summary import _format_now
from .top_trending_briefing import SHEET_LABELS


# 涨跌颜色沿用国内习惯：上涨红、下跌绿，与榜单排名变化配色一致。
RISE_COLOR = "red"
FALL_COLOR = "green"
HIGHLIGHT_NAME_COLOR = "blue"
FAILURE_COLOR = "red"
# 次要信息（品类、日期、Robux 等）统一用灰色，让名字、涨跌和金额更突出。
SECONDARY_COLOR = "grey"
# 标题栏颜色：有数据异常时换成橙色，进群一眼就能看出今天的数据是否完整。
HEADER_TEMPLATE = "blue"
HEADER_TEMPLATE_WITH_FAILURES = "orange"
# 大盘结论：看在玩榜前 100 合计在线较上周同日的变化；平稳不上色。
MARKET_TREND_TEXTS: dict[MarketTrend, tuple[str, str]] = {
    "up": ("大盘上涨", RISE_COLOR),
    "flat": ("大盘平稳", ""),
    "down": ("大盘下滑", FALL_COLOR),
}
# 底部备注的触发方式；不显示触发人的用户 ID。
BRIEF_TRIGGER_TEXTS = {
    SCHEDULED_TRIGGER_SOURCE: "定时",
    "feishu_chat_command": "手动（飞书命令）",
    "workflow_dispatch": "手动（GitHub Actions）",
}
STANDOUT_MARK = "🔥"
# 栏目标题的表情：每栏只出现一次，起分段作用。
NEW_FACE_MARK = "🆕"
GROWTH_MARK = "📈"
LONG_TERM_MARK = "🌱"
NEW_GAME_LEADER_MARK = "👑"
# 条目里的标识不用彩色表情（表情跟文字一样大，会盖过游戏名），只用普通符号和浅色文字，不加粗，
# 让每行唯一加粗的蓝色游戏名最醒目。色阶（-400）写法见飞书卡片“颜色枚举值”文档；
# 1.0 卡片 markdown 是否支持文档未写明，2026-11-11 上线时待实测，不生效时改回 orange、red 等默认色。
# 增长证据的颜色：在线涨幅、晋榜、收入榜上升。收入不用蓝色，避免与蓝色的游戏名混在一起。
EVIDENCE_COLORS: dict[EvidenceKind, str] = {
    "ccu": "red-400",
    "board_entry": "orange-400",
    "earning": "purple-400",
}
# 头部新游趋势的结论：符号、文字、颜色。涨红跌绿与其他涨跌一致。
LEADER_STATE_TEXTS: dict[LeaderState, tuple[str, str, str]] = {
    "up": ("▲", "上升", "red-400"),
    "flat": ("–", "平稳", "grey"),
    "down": ("▼", "回落", "green-400"),
    "new": ("＋", "新晋", "orange-400"),
}
# 留存结论：符号、文字、颜色。
RETENTION_TEXTS: dict[RetentionTier, tuple[str, str, str]] = {
    "good": ("●", "留得住", "green-400"),
    "watch": ("◐", "待观察", "grey"),
    "bad": ("○", "留不住", "red-400"),
}
# 条目第二行起的缩进，用全角空格，飞书不会折叠。
SUB_LINE_INDENT = "　"
# 游戏名后的 Rotrends 详情页链接，方便点开看在线曲线；只放链接，不抓取也不展示它的数据。
ROTRENDS_GAME_URL = "https://www.rotrends.com/game/{universe_id}"
# 自家项目的状态标记：全部上涨、全部下跌、涨跌都有、没有提醒。
PROJECT_RISE_MARK = "🔴"
PROJECT_FALL_MARK = "🟢"
PROJECT_MIXED_MARK = "🟠"
PROJECT_STEADY_MARK = "⚪"
# 字号：段落标题放大；旧版客户端不支持时按正常字号显示。
SECTION_TITLE_TEXT_SIZE = "heading"
# 灰底面板，用于“今日最突出”。
PANEL_BACKGROUND = "grey"
# CCU 达到一万时改用“万”为单位展示，便于中文阅读。
TEN_THOUSAND = 10_000

CardElement = dict[str, object]


def build_daily_brief_card(cfg: Config, content: DailyBriefContent, *, show_revenue: bool) -> dict[str, object]:
    """组装一张早报卡片；show_revenue 只对全量群为 True。"""

    sections: list[list[CardElement]] = []
    sections.append(_build_market_section(content.market))
    sections.append(_build_projects_section(content.projects))
    if show_revenue:
        sections.append(_build_revenue_section(content.revenues))
    if content.failures:
        sections.append(_build_failure_section(content))

    elements: list[CardElement] = []
    for index, section in enumerate(sections):
        if index:
            elements.append({"tag": "hr"})
        elements.extend(section)
    elements.append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"时间：{_format_now(cfg.feishu_timezone)}（{cfg.feishu_timezone}）"
                    f"｜触发：{BRIEF_TRIGGER_TEXTS.get(cfg.run_trigger_source, '手动')}",
                }
            ],
        }
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": HEADER_TEMPLATE_WITH_FAILURES if content.failures else HEADER_TEMPLATE,
            "title": {"tag": "plain_text", "content": f"📰 每日早报（{content.brief_date}）"},
        },
        "elements": elements,
    }


def strip_project_title(title: str) -> str:
    """去掉表格标题里的固定后缀，得到简洁的项目名。"""

    stripped = title.strip()
    for suffix in PROJECT_TITLE_SUFFIXES_TO_STRIP:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].strip()
    return stripped or title.strip()


def _build_market_section(market: MarketSection | None) -> list[CardElement]:
    elements = [_section_title("📈 行业趋势")]
    if market is None:
        elements.append(_markdown("今日榜单数据延迟，详见下方数据异常。"))
        return elements

    if market.pulse is not None:
        elements.append(_build_pulse_line(market.pulse))
    if market.genre_lines:
        elements.append(_markdown("\n".join(f"- **品类风向**：{line}" for line in market.genre_lines)))
    elements.extend(_build_spotlight_elements(market.spotlight))
    return elements


def _build_pulse_line(pulse: MarketPulse) -> CardElement:
    """大盘一行：结论在前，看较上周同日（同一个星期几相比，抵消周末效应），后面是合计在线与涨跌。

    缺少上周同日数据时写“暂不判断”，不改用其他日期。
    """

    week_change = pulse.broad_week_change
    if week_change is None:
        conclusion = f"**大盘暂不判断**{_color('（缺少上周同日数据）', SECONDARY_COLOR)}"
    else:
        text, color = MARKET_TREND_TEXTS[week_change.trend]
        conclusion = f"**{_color(text, color)}**" if color else f"**{text}**"
    changes: list[str] = []
    if pulse.broad_day_change is not None:
        changes.append(f"较昨天 {_format_ratio(pulse.broad_day_change.change_ratio)}")
    if week_change is not None:
        changes.append(f"较上周同日 {_format_ratio(week_change.change_ratio)}")
    detail = f"在玩榜前 {MARKET_PULSE_BROAD_SIZE} 合计 {_format_ccu(pulse.snapshot.broad_ccu)}"
    if changes:
        detail += f"（{'，'.join(changes)}）"
    else:
        detail += _color(f"（数据积累中，已记录 {pulse.recorded_days} 天）", SECONDARY_COLOR)
    return _markdown(f"{conclusion}｜{detail}")


def _build_spotlight_elements(spotlight: MarketSpotlight) -> list[CardElement]:
    """值得关注项目：两个今日最突出，其后依次是新面孔、增长快、长线潜力、头部新游。"""

    elements: list[CardElement] = []
    if spotlight.new_face_standout is not None:
        elements.append(_build_standout_panel("新面孔", spotlight.new_face_standout, is_new_face=True))
    if spotlight.growth_standout is not None:
        elements.append(_build_standout_panel("增长快", spotlight.growth_standout, is_new_face=False))
    elements.append(_build_new_face_element(spotlight))
    elements.append(_build_growth_element(spotlight))
    elements.append(_build_long_term_element(spotlight))
    if spotlight.new_game_leaders:
        elements.append(_build_new_game_leaders_element(spotlight.new_game_leaders))
    return elements


def _build_standout_panel(group_label: str, standout: SpotlightEntry, *, is_new_face: bool) -> CardElement:
    """“今日最突出”放进灰底面板，与其余条目拉开层级；留存结论总是写出，便于判断是不是昙花一现。"""

    # 栏目说明用灰色不加粗，只让游戏名加粗突出。
    title = f"{STANDOUT_MARK} {_color(f'今日最突出 · {group_label}：', SECONDARY_COLOR)}{_format_entry_name(standout)}"
    if is_new_face:
        lines = [title, _format_new_face_details(standout)]
    else:
        lines = [title, _format_entry_basics(standout), _format_evidence_line(standout)]
    if standout.retention is not None:
        lines.append(_format_retention(standout.retention))
    else:
        lines.append(_color("留存数据积累中", SECONDARY_COLOR))
    return _panel([_column([_markdown("\n".join(lines))])], flex_mode="none")


def _build_new_face_element(spotlight: MarketSpotlight) -> CardElement:
    """新面孔：最近若干天没上过榜的新游，按 CCU 排列；排名靠后的不展示，标题写明总数。"""

    title = f"**{NEW_FACE_MARK} 新面孔**"
    if spotlight.new_face_lookback_days == 0:
        return _markdown(f"{title}\n{_color('历史快照不可用，今天无法判断，详见下方数据异常。', SECONDARY_COLOR)}")
    # 历史不足回看天数时如实写出实际回看了几天。
    lookback_days = min(spotlight.new_face_lookback_days, NEW_FACE_LOOKBACK_DAYS)
    total = len(spotlight.all_new_faces)
    scope = f"（{_format_shown_count(total, spotlight.new_face_overflow)}｜近 {lookback_days} 天没上过榜、{_format_scope()}）"
    lines = [f"{title} {_color(scope, SECONDARY_COLOR)}"]
    if total == 0:
        lines.append(_color("今天没有新面孔。", SECONDARY_COLOR))
    lines.extend(_format_entry_item(entry, is_new_face=True) for entry in spotlight.new_faces)
    return _markdown("\n".join(lines))


def _build_growth_element(spotlight: MarketSpotlight) -> CardElement:
    """增长快：在线、晋榜、收入任一类证据成立的新游，证据多的在前；排名靠后的不展示，标题写明总数。"""

    total = len(spotlight.all_growth)
    scope = f"（{_format_shown_count(total, spotlight.growth_overflow)}｜{_format_scope()}）"
    lines = [f"**{GROWTH_MARK} 增长快** {_color(scope, SECONDARY_COLOR)}"]
    if total == 0:
        lines.append(_color("今天没有增长明显的新游。", SECONDARY_COLOR))
    lines.extend(_format_entry_item(entry, is_new_face=False) for entry in spotlight.growth)
    return _markdown("\n".join(lines))


def _format_shown_count(total: int, hidden: tuple[SpotlightEntry, ...]) -> str:
    """栏目总数；有没展示的游戏时写明展示了前几款（含今日最突出），完整名单在明细产物里。"""

    if not hidden:
        return f"共 {total} 款"
    return f"共 {total} 款，展示前 {total - len(hidden)} 款"


def _format_scope() -> str:
    return f"创建 {SPOTLIGHT_MAX_GAME_AGE_DAYS} 天内、CCU ≥{SPOTLIGHT_MIN_CCU:,}"


def _build_new_game_leaders_element(leaders: tuple[SpotlightEntry, ...]) -> CardElement:
    """头部新游趋势：在玩榜排名最高的几款新游，每款只写势头结论和解释它的两个在线人数。"""

    scope = "（在玩榜排名最高的新游，在线较上周同日）"
    lines = [f"**{NEW_GAME_LEADER_MARK} 头部新游趋势** {_color(scope, SECONDARY_COLOR)}"]
    lines.extend(
        f"- {_format_entry_name(entry)}：{_format_leader_status(entry.leader)}"
        for entry in leaders
        if entry.leader is not None
    )
    return _markdown("\n".join(lines))


def _format_entry_item(entry: SpotlightEntry, *, is_new_face: bool) -> str:
    """列表里的一款游戏。新面孔只占一行（栏目已说明是新面孔，不再重复）；
    增长快第二行是增长证据；留不住时再加一行提醒是昙花一现。
    """

    if is_new_face:
        lines = [f"- {_format_entry_name(entry)} {_format_new_face_details(entry)}"]
    else:
        lines = [
            f"- {_format_entry_name(entry)} {_format_entry_basics(entry)}",
            f"{SUB_LINE_INDENT}{_format_evidence_line(entry)}",
        ]
    if entry.retention is not None and entry.retention.tier == "bad":
        lines.append(f"{SUB_LINE_INDENT}{_format_retention(entry.retention)}")
    return "\n".join(lines)


def _format_entry_name(entry: SpotlightEntry) -> str:
    return f"**{_color(entry.name, HIGHLIGHT_NAME_COLOR)}**{_format_rotrends_link(entry)}"


def _format_rotrends_link(entry: SpotlightEntry) -> str:
    if not entry.universe_id:
        return ""
    return f" [Rotrends]({ROTRENDS_GAME_URL.format(universe_id=entry.universe_id)})"


def _format_entry_basics(entry: SpotlightEntry) -> str:
    """灰色基本信息：品类、CCU、上线天数。"""

    return _color("｜".join(_entry_basic_parts(entry)), SECONDARY_COLOR)


def _entry_basic_parts(entry: SpotlightEntry) -> list[str]:
    parts = [entry.genre or "-", _format_entry_ccu(entry)]
    if entry.age_days is not None:
        parts.append(f"上线 {entry.age_days} 天")
    return parts


def _format_new_face_details(entry: SpotlightEntry) -> str:
    """新面孔一行里的信息：品类、CCU、上线天数，以及它出现在哪个榜单；进了收入榜时附收入榜位置。"""

    parts = _entry_basic_parts(entry)
    ranks = _format_sheet_ranks(entry)
    if ranks:
        parts.append(ranks)
    return _color("｜".join(parts), SECONDARY_COLOR) + _format_earning_detail(entry)


def _format_entry_ccu(entry: SpotlightEntry) -> str:
    """采样足够时展示全天平均；否则只有抓取时刻的值，明确标为当次，避免被当成全天水平比较。"""

    if entry.average_ccu is None:
        return f"当次 CCU {entry.ccu:,}"
    return f"日均 CCU {entry.average_ccu:,}"


def _format_evidence_line(entry: SpotlightEntry) -> str:
    """增长快的第二行：增长证据，连续增长两天以上时注明，进了收入榜时附收入榜位置。

    榜单名次与上榜天数不再列出：证据里已说明是哪个榜，规模看第一行的 CCU，新旧看上线天数。
    """

    streak = (
        _color(f"｜连续第 {entry.growth_streak_days} 天增长", SECONDARY_COLOR) if entry.growth_streak_days >= 2 else ""
    )
    # 收入证据已写了较上次的变化（如“收入榜 ↑66”），收入榜位置后面不再重复。
    has_earning_evidence = any(item.kind == "earning" for item in entry.evidence)
    earning = _format_earning_detail(entry, include_change=not has_earning_evidence)
    return f"{_format_evidence_badges(entry)}{streak}{earning}"


def _format_evidence_badges(entry: SpotlightEntry) -> str:
    """各条增长证据用浅色文字列出，不加粗、不带表情，避免抢过游戏名。"""

    return SUB_LINE_INDENT.join(_color(item.text, EVIDENCE_COLORS[item.kind]) for item in entry.evidence)


def _format_retention(retention: RetentionVerdict) -> str:
    """结论在前，后面是推出它的数据，例如“● 留得住｜单局约 33 分钟 · 在线守住 14 日峰值的 100%”。

    单局时长是用公开的在线人数和访问量估算的，所以写“约”；好评率高不代表留得住，只在偏低时作为警告写出。
    """

    mark, label, color = RETENTION_TEXTS[retention.tier]
    facts: list[str] = []
    if retention.session_minutes is not None:
        facts.append(f"单局约 {retention.session_minutes:.0f} 分钟")
    elif retention.session_note == "afk":
        facts.append("疑似挂机，单局时长不参与判断")
    else:
        facts.append("单局时长暂无（采样不足）")
    if retention.peak_ratio is not None:
        facts.append(f"在线守住 {LONG_TERM_PEAK_WINDOW_DAYS} 日峰值的 {min(retention.peak_ratio, 1):.0%}")
    if retention.like_ratio is not None and retention.like_ratio < RETENTION_BAD_LIKE_RATIO:
        # 向下取整：74.8% 四舍五入成 75% 会和“低于 75% 才算偏低”自相矛盾。
        facts.append(f"好评仅 {int(round(retention.like_ratio * 100, 6))}%")
    return f"{_color(f'{mark} {label}', color)}｜{' · '.join(facts)}"


def _build_long_term_element(spotlight: MarketSpotlight) -> CardElement:
    """长线潜力：留得住、且新面孔和增长快卡片上没展示的新游；历史快照不足时提示还要积累几天。"""

    title = f"**{LONG_TERM_MARK} 长线潜力**"
    if spotlight.long_term:
        lines = [title]
        lines.extend(
            f"- {_format_entry_name(entry)}：{_format_retention(entry.retention)}"
            for entry in spotlight.long_term
            if entry.retention is not None
        )
        return _markdown("\n".join(lines))
    if spotlight.long_term_recorded_days < LONG_TERM_MIN_RECORDED_DAYS:
        remaining_days = LONG_TERM_MIN_RECORDED_DAYS - spotlight.long_term_recorded_days
        hint = f"数据积累中（已记录 {spotlight.long_term_recorded_days} 天，还需 {remaining_days} 天）"
    else:
        hint = "今天没有其他留得住的新游。"
    return _markdown(f"{title}\n{_color(hint, SECONDARY_COLOR)}")


def _format_sheet_ranks(entry: SpotlightEntry) -> str:
    """各榜单排名；收入榜单独由 _format_earning_detail 展示变化，这里不重复。"""

    return "、".join(
        f"{label} #{rank}" for label, rank in entry.sheet_ranks if label != SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    )


def _format_earning_detail(entry: SpotlightEntry, *, include_change: bool = True) -> str:
    """收入榜位置与变化，只在进了收入榜考察范围时写；上升红、下降绿，与其他涨跌配色一致。

    include_change 为 False 时不写较上次的变化，用于增长证据里已经写过的情况。
    """

    label = SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    earning = entry.earning
    if earning is None:
        return ""
    changes: list[str] = []
    if include_change and earning.change:
        changes.append(f"较上次 {_format_rank_change(earning.change)}")
    if earning.entered_this_week:
        changes.append("一周前不在榜")
    elif earning.week_change:
        changes.append(f"一周 {_format_rank_change(earning.week_change)}")
    suffix = f"（{'，'.join(changes)}）" if changes else ""
    return f"｜{label} #{earning.rank}{suffix}"


def _format_leader_status(leader: LeaderStatus) -> str:
    """结论在前，后面是解释它的数据，例如“▲ 上升｜在线 7.7 万 → 19.5 万（较上周同日 +153%）”。"""

    if leader.state is None:
        return _color(f"在线 {_format_ccu(leader.ccu)}｜缺少上周同日数据，今天不判断", SECONDARY_COLOR)
    mark, label, color = LEADER_STATE_TEXTS[leader.state]
    conclusion = _color(f"{mark} {label}", color)
    if leader.ccu_week_ago is None or leader.week_change is None:
        return f"{conclusion}｜在线 {_format_ccu(leader.ccu)}（一周前未上榜）"
    return (
        f"{conclusion}｜在线 {_format_ccu(leader.ccu_week_ago)} → {_format_ccu(leader.ccu)}"
        f"（较上周同日 {_format_ratio(leader.week_change)}）"
    )


def _format_rank_change(change: int) -> str:
    if change > 0:
        return _color(f"↑{change}", RISE_COLOR)
    return _color(f"↓{-change}", FALL_COLOR)


def _build_projects_section(projects: tuple[ProjectBriefEntry, ...]) -> list[CardElement]:
    """统计日期相同时写在栏目标题里，只有个别项目日期不同才在那一行单独写。"""

    common_date = _common_date(entry.trend.report_date for entry in projects if entry.trend is not None)
    elements = [_section_title(f"🎮 自家项目（{common_date}）" if common_date else "🎮 自家项目")]
    if not projects:
        elements.append(_markdown(_color("没有可展示的项目数据。", SECONDARY_COLOR)))
        return elements
    # 有提醒的项目排在前面，其余保持原有顺序。
    ordered = sorted(projects, key=lambda entry: not (entry.trend is not None and entry.trend.alerts))
    elements.append(_markdown("\n".join(_build_project_line(entry, common_date) for entry in ordered)))
    return elements


def _common_date(dates) -> str:
    """所有日期都相同时返回该日期，否则返回空串（没有日期时也为空）。"""

    unique = set(dates)
    return unique.pop() if len(unique) == 1 else ""


def _build_project_line(entry: ProjectBriefEntry, common_date: str = "") -> str:
    """有提醒时只列提醒，没有提醒时用灰色列核心数字；没出数的指标写“待出”。项目名链接到它的日报表格。"""

    name = f"[{entry.name}]({entry.sheet_url})" if entry.sheet_url else entry.name
    trend = entry.trend
    if trend is None:
        return f"{PROJECT_STEADY_MARK} **{name}** {_color('表格暂无数据', SECONDARY_COLOR)}"
    date_text = _color(f"（{trend.report_date}）", SECONDARY_COLOR) if trend.report_date != common_date else ""
    if trend.alerts:
        detail = "；".join(_format_alert(alert) for alert in trend.alerts)
        return f"{_project_alert_mark(trend.alerts)} **{name}**{date_text}：{detail}"
    if any(value for _, value in trend.summary_values):
        summary = "｜".join(f"{label} {value or '待出'}" for label, value in trend.summary_values)
    else:
        summary = "核心数字未出"
    return f"{PROJECT_STEADY_MARK} **{name}**{date_text}：{_color(summary, SECONDARY_COLOR)}"


def _project_alert_mark(alerts: tuple[MetricAlert, ...]) -> str:
    directions = {alert.direction for alert in alerts}
    if directions == {"rise"}:
        return PROJECT_RISE_MARK
    if directions == {"fall"}:
        return PROJECT_FALL_MARK
    return PROJECT_MIXED_MARK


def _build_revenue_section(revenues: tuple[RevenueBriefEntry, ...]) -> list[CardElement]:
    common_date = _common_date(entry.revenue.report_date for entry in revenues)
    elements = [_section_title(f"💰 收入（截至 {common_date}）" if common_date else "💰 收入")]
    if not revenues:
        elements.append(_markdown(_color("没有可展示的收入数据。", SECONDARY_COLOR)))
        return elements
    lines: list[str] = []
    for entry in revenues:
        revenue = entry.revenue
        # 统计日期相同时已写在栏目标题里，只有个别项目日期不同才单独写。
        report_date = (
            _color(f"（截至 {revenue.report_date}）", SECONDARY_COLOR) if revenue.report_date != common_date else ""
        )
        robux = _color(f"（{format_robux(revenue.daily_robux)} Robux）", SECONDARY_COLOR)
        line = (
            f"- **{strip_project_title(revenue.project_name)}**{report_date}："
            f"当日 **{format_usd(revenue.daily_usd)}** {robux}"
            f"｜月累计 {format_usd(revenue.month_to_date_usd)}"
        )
        if entry.alert is not None:
            line += f"｜{_format_alert(entry.alert, include_value=False)}"
        lines.append(line)
    elements.append(_markdown("\n".join(lines)))
    return elements


def _build_failure_section(content: DailyBriefContent) -> list[CardElement]:
    """同一原因的故障合并成一行，例如 Cookie 失效时不重复列出每个项目。"""

    labels_by_reason: dict[str, list[str]] = {}
    for failure in content.failures:
        labels_by_reason.setdefault(failure.reason, []).append(failure.label)
    lines = [f"- {_color('、'.join(labels), FAILURE_COLOR)}：{reason}" for reason, labels in labels_by_reason.items()]
    return [_section_title("⚠️ 数据异常"), _markdown("\n".join(lines))]


def _format_alert(alert: MetricAlert, *, include_value: bool = True) -> str:
    arrow, color = ("↑", RISE_COLOR) if alert.direction == "rise" else ("↓", FALL_COLOR)
    value_text = f" {alert.current_text}" if include_value else ""
    return _color(
        f"{arrow} {alert.label}{value_text}（较 {PROJECT_TREND_BASELINE_DAYS} 日均 {_format_ratio(alert.change_ratio)}）",
        color,
    )


def _format_ratio(ratio: float) -> str:
    return f"{ratio * 100:+.0f}%"


def _format_ccu(value: int) -> str:
    if value >= TEN_THOUSAND:
        return f"{value / TEN_THOUSAND:,.1f} 万"
    return f"{value:,}"


def _section_title(text: str) -> CardElement:
    return _markdown(f"**{text}**", text_size=SECTION_TITLE_TEXT_SIZE)


def _panel(columns: list[CardElement], *, flex_mode: str) -> CardElement:
    return {
        "tag": "column_set",
        "flex_mode": flex_mode,
        "background_style": PANEL_BACKGROUND,
        "columns": columns,
    }


def _column(elements: list[CardElement]) -> CardElement:
    return {"tag": "column", "width": "weighted", "weight": 1, "vertical_align": "top", "elements": elements}


def _markdown(content: str, *, text_size: str = "") -> CardElement:
    element: CardElement = {"tag": "markdown", "content": content}
    if text_size:
        element["text_size"] = text_size
    return element


def _color(text: str, color: str) -> str:
    return f"<font color='{color}'>{text}</font>"
