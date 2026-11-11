"""把早报内容组装成飞书卡片。"""

from __future__ import annotations

from .config import Config
from .daily_brief_models import DailyBriefContent, MarketSection, ProjectBriefEntry, RevenueBriefEntry
from .daily_brief_rules import (
    LONG_TERM_MIN_RECORDED_DAYS,
    LONG_TERM_PEAK_WINDOW_DAYS,
    MARKET_PULSE_BROAD_SIZE,
    MARKET_PULSE_HEAD_SIZE,
    NEW_FACE_LOOKBACK_DAYS,
    PROJECT_TITLE_SUFFIXES_TO_STRIP,
    PROJECT_TREND_BASELINE_DAYS,
    RETENTION_BAD_LIKE_RATIO,
    SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK,
    SPOTLIGHT_MAX_GAME_AGE_DAYS,
    SPOTLIGHT_MIN_CCU,
)
from .market_pulse import MarketChange, MarketPulse
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
from .summary import _format_now, _format_trigger
from .top_trending_briefing import SHEET_LABELS


# 涨跌颜色沿用国内习惯：上涨红、下跌绿，与榜单排名变化配色一致。
RISE_COLOR = "red"
FALL_COLOR = "green"
FLAT_TREND_TEXT = "平稳"
HIGHLIGHT_NAME_COLOR = "blue"
FAILURE_COLOR = "red"
# 次要信息（品类、日期、Robux 等）统一用灰色，让名字、涨跌和金额更突出。
SECONDARY_COLOR = "grey"
# 标题栏颜色：有数据异常时换成橙色，进群一眼就能看出今天的数据是否完整。
HEADER_TEMPLATE = "blue"
HEADER_TEMPLATE_WITH_FAILURES = "orange"
STANDOUT_MARK = "🔥"
# 栏目标题的表情：每栏只出现一次，起分段作用。
NEW_FACE_MARK = "🆕"
GROWTH_MARK = "📈"
LONG_TERM_MARK = "🌱"
NEW_GAME_LEADER_MARK = "👑"
# 条目里的标识不用彩色表情（表情跟文字一样大，会盖过游戏名），只用普通符号和浅色文字，不加粗，
# 让每行唯一加粗的蓝色游戏名最醒目。色阶（-400）写法见飞书卡片“颜色枚举值”文档；
# 1.0 卡片 markdown 是否支持文档未写明，2026-11-11 上线时待实测，不生效时改回 orange、red 等默认色。
NEW_FACE_COLOR = "orange-400"
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
# 字号：段落标题与大盘数字放大，标签缩小；旧版客户端不支持时按正常字号显示。
SECTION_TITLE_TEXT_SIZE = "heading"
KPI_VALUE_TEXT_SIZE = "heading-2"
KPI_LABEL_TEXT_SIZE = "notation"
# 灰底面板，用于大盘数字和“今日最突出”。
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
                    f"｜触发：{_format_trigger(cfg)}",
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
        elements.append(_build_pulse_columns(market.pulse))
    if market.genre_lines:
        elements.append(_markdown("\n".join(f"- **品类风向**：{line}" for line in market.genre_lines)))
    elements.extend(_build_spotlight_elements(market.spotlight))
    return elements


def _build_pulse_columns(pulse: MarketPulse) -> CardElement:
    """大盘与头部并排展示：灰色小字标签、放大的在线人数、涨跌。"""

    snapshot = pulse.snapshot
    broad_label = f"大盘 · 在玩榜前 {MARKET_PULSE_BROAD_SIZE}"
    if snapshot.game_count < MARKET_PULSE_BROAD_SIZE:
        broad_label += f"（实际 {snapshot.game_count} 款）"
    return _panel(
        [
            _build_pulse_column(
                broad_label,
                snapshot.broad_ccu,
                pulse.broad_day_change,
                pulse.broad_week_change,
                pulse.recorded_days,
            ),
            _build_pulse_column(
                f"头部 · 前 {MARKET_PULSE_HEAD_SIZE}",
                snapshot.head_ccu,
                pulse.head_day_change,
                pulse.head_week_change,
                pulse.recorded_days,
            ),
        ],
        flex_mode="bisect",
    )


def _build_pulse_column(
    label: str,
    ccu: int,
    day_change: MarketChange | None,
    week_change: MarketChange | None,
    recorded_days: int,
) -> CardElement:
    return _column(
        [
            _markdown(_color(label, SECONDARY_COLOR), text_size=KPI_LABEL_TEXT_SIZE),
            _markdown(f"**{_format_ccu(ccu)}**", text_size=KPI_VALUE_TEXT_SIZE),
            _markdown(_format_pulse_changes(day_change, week_change, recorded_days)),
        ]
    )


def _format_pulse_changes(
    day_change: MarketChange | None,
    week_change: MarketChange | None,
    recorded_days: int,
) -> str:
    """有对比数据时逐行展示涨跌，否则提示历史数据仍在积累。"""

    lines: list[str] = []
    if day_change is not None:
        lines.append(f"较昨日 {_format_market_change(day_change)}")
    if week_change is not None:
        lines.append(f"较上周同日 {_format_market_change(week_change)}")
    if not lines:
        return _color(f"数据积累中（已记录 {recorded_days} 天）", SECONDARY_COLOR)
    return "\n".join(lines)


def _format_market_change(change: MarketChange) -> str:
    ratio_text = _format_ratio(change.change_ratio)
    if change.trend == "up":
        return f"**{_color(f'{ratio_text} ↑', RISE_COLOR)}**"
    if change.trend == "down":
        return f"**{_color(f'{ratio_text} ↓', FALL_COLOR)}**"
    return _color(f"{ratio_text}（{FLAT_TREND_TEXT}）", SECONDARY_COLOR)


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
    lines = [
        f"{STANDOUT_MARK} {_color(f'今日最突出 · {group_label}：', SECONDARY_COLOR)}{_format_entry_name(standout)}",
        _format_entry_basics(standout),
        _format_badge_line(standout, is_new_face=is_new_face),
    ]
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
    """列表里的一款游戏：第一行名字与基本信息，第二行标识；留不住时再加一行提醒是昙花一现。"""

    lines = [
        f"- {_format_entry_name(entry)} {_format_entry_basics(entry)}",
        f"{SUB_LINE_INDENT}{_format_badge_line(entry, is_new_face=is_new_face)}",
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

    parts = [entry.genre or "-", _format_entry_ccu(entry)]
    if entry.age_days is not None:
        parts.append(f"上线 {entry.age_days} 天")
    return _color("｜".join(parts), SECONDARY_COLOR)


def _format_entry_ccu(entry: SpotlightEntry) -> str:
    """采样足够时展示全天口径；否则只有抓取时刻的值，明确标为当次，避免被当成全天水平比较。"""

    if entry.average_ccu is None or entry.peak_ccu is None:
        return f"当次 CCU {entry.ccu:,}"
    return f"日均 CCU {entry.average_ccu:,}｜近似峰值 {entry.peak_ccu:,}"


def _format_badge_line(entry: SpotlightEntry, *, is_new_face: bool) -> str:
    """标识行：新面孔或各条增长证据，后面跟榜单位置、上榜天数和收入榜情况。"""

    badge = _color("新面孔", NEW_FACE_COLOR) if is_new_face else _format_evidence_badges(entry)
    notes = [_format_sheet_ranks(entry)]
    # 新面孔当天一定是上榜第 1 天，不必再写。
    if not is_new_face and entry.days_on_board is not None:
        notes.append(f"上榜第 {entry.days_on_board} 天")
    if entry.growth_streak_days >= 2:
        notes.append(f"连续第 {entry.growth_streak_days} 天增长")
    details = _color("｜".join(note for note in notes if note), SECONDARY_COLOR)
    return f"{badge} {details}{_format_earning_detail(entry, show_missing=True)}"


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


def _format_earning_detail(entry: SpotlightEntry, *, show_missing: bool = False) -> str:
    """收入榜位置与变化，跟在灰色信息后面；上升红、下降绿，与其他涨跌配色一致。

    show_missing 为 True 时，不在收入榜考察范围内也如实写明：在线涨得快但看不到收入，不估算。
    """

    label = SHEET_LABELS[TOP_EARNING_SHEET_KEY]
    earning = entry.earning
    if earning is None:
        if not show_missing:
            return ""
        return _color(f"｜{label}：未进前 {SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK}", SECONDARY_COLOR)
    changes: list[str] = []
    if earning.change:
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
    elements = [_section_title("🎮 自家项目")]
    if not projects:
        elements.append(_markdown(_color("没有可展示的项目数据。", SECONDARY_COLOR)))
        return elements
    # 有提醒的项目排在前面，其余保持原有顺序。
    ordered = sorted(projects, key=lambda entry: not (entry.trend is not None and entry.trend.alerts))
    elements.append(_markdown("\n".join(_build_project_line(entry) for entry in ordered)))
    return elements


def _build_project_line(entry: ProjectBriefEntry) -> str:
    """有提醒时只列提醒，没有提醒时用灰色列核心数字；项目名链接到它的日报表格。"""

    name = f"[{entry.name}]({entry.sheet_url})" if entry.sheet_url else entry.name
    trend = entry.trend
    if trend is None:
        return f"{PROJECT_STEADY_MARK} **{name}** {_color('表格暂无数据', SECONDARY_COLOR)}"
    date_text = _color(f"（{trend.report_date}）", SECONDARY_COLOR)
    if trend.alerts:
        detail = "；".join(_format_alert(alert) for alert in trend.alerts)
        return f"{_project_alert_mark(trend.alerts)} **{name}**{date_text}：{detail}"
    summary = "｜".join(f"{label} {value}" for label, value in trend.summary_values) or "核心数字未出"
    return f"{PROJECT_STEADY_MARK} **{name}**{date_text}：{_color(summary, SECONDARY_COLOR)}"


def _project_alert_mark(alerts: tuple[MetricAlert, ...]) -> str:
    directions = {alert.direction for alert in alerts}
    if directions == {"rise"}:
        return PROJECT_RISE_MARK
    if directions == {"fall"}:
        return PROJECT_FALL_MARK
    return PROJECT_MIXED_MARK


def _build_revenue_section(revenues: tuple[RevenueBriefEntry, ...]) -> list[CardElement]:
    elements = [_section_title("💰 收入")]
    if not revenues:
        elements.append(_markdown(_color("没有可展示的收入数据。", SECONDARY_COLOR)))
        return elements
    lines: list[str] = []
    for entry in revenues:
        revenue = entry.revenue
        report_date = _color(f"（截至 {revenue.report_date}）", SECONDARY_COLOR)
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
