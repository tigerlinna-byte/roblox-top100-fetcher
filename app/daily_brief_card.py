"""把早报内容组装成飞书卡片。"""

from __future__ import annotations

from .config import Config
from .daily_brief_models import DailyBriefContent, MarketSection, ProjectBriefEntry, RevenueBriefEntry
from .daily_brief_rules import (
    LONG_TERM_MIN_RECORDED_DAYS,
    MARKET_PULSE_BROAD_SIZE,
    MARKET_PULSE_HEAD_SIZE,
    PROJECT_TITLE_SUFFIXES_TO_STRIP,
    PROJECT_TREND_BASELINE_DAYS,
)
from .market_pulse import MarketChange, MarketPulse
from .market_spotlight import MarketSpotlight, SpotlightEntry
from .metric_baseline import MetricAlert
from .roblox_money_summary import format_robux, format_usd
from .summary import _format_now, _format_trigger


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
LONG_TERM_MARK = "🌱"
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
    elements: list[CardElement] = []
    if spotlight.standout is None and not spotlight.entries and not spotlight.long_term:
        elements.append(_markdown(_color("今天没有发现值得特别关注的项目。", SECONDARY_COLOR)))
        elements.append(_build_long_term_element(spotlight))
        return elements

    if spotlight.standout is not None:
        elements.append(_build_standout_panel(spotlight.standout))
    elements.append(_build_long_term_element(spotlight))
    if spotlight.entries:
        lines = ["**👀 值得关注**"]
        for entry in spotlight.entries:
            name = f"**{_color(entry.name, HIGHLIGHT_NAME_COLOR)}**"
            details = _color(f"｜{entry.genre or '-'}｜CCU {entry.ccu:,}", SECONDARY_COLOR)
            lines.append(f"- {name}：{_format_spotlight_reasons(entry)} {details}")
        elements.append(_markdown("\n".join(lines)))
    return elements


def _build_standout_panel(standout: SpotlightEntry) -> CardElement:
    """“今日最突出”放进灰底面板，与其余条目拉开层级。"""

    details = f"{standout.genre or '-'}｜CCU {standout.ccu:,}"
    sheet_ranks = _format_sheet_ranks(standout)
    if sheet_ranks:
        details += f"｜{sheet_ranks}"
    lines = [
        f"{STANDOUT_MARK} **今日最突出（爆发）：{_color(standout.name, HIGHLIGHT_NAME_COLOR)}**",
        _format_spotlight_reasons(standout),
    ]
    # 爆发的游戏也附上长线指标，便于判断是昙花一现还是能留住人。
    if standout.long_term_signals:
        lines.append(f"长线 {standout.long_term_score} 分：{_format_long_term_reasons(standout)}")
    lines.append(_color(details, SECONDARY_COLOR))
    return _panel([_column([_markdown("\n".join(lines))])], flex_mode="none")


def _build_long_term_element(spotlight: MarketSpotlight) -> CardElement:
    """长线潜力：列出长线分最高的游戏及依据；历史快照不足时提示还要积累几天。"""

    title = f"**{LONG_TERM_MARK} 长线潜力**"
    if spotlight.long_term:
        lines = [title]
        for entry in spotlight.long_term:
            name = f"**{_color(entry.name, HIGHLIGHT_NAME_COLOR)}**"
            details = _color(f"｜{entry.genre or '-'}｜CCU {entry.ccu:,}", SECONDARY_COLOR)
            lines.append(f"- {name}：长线 {entry.long_term_score} 分｜{_format_long_term_reasons(entry)} {details}")
        return _markdown("\n".join(lines))
    if spotlight.long_term_recorded_days < LONG_TERM_MIN_RECORDED_DAYS:
        remaining_days = LONG_TERM_MIN_RECORDED_DAYS - spotlight.long_term_recorded_days
        hint = f"数据积累中（已记录 {spotlight.long_term_recorded_days} 天，还需 {remaining_days} 天）"
    else:
        hint = "今天没有长线分达到门槛的项目。"
    return _markdown(f"{title}\n{_color(hint, SECONDARY_COLOR)}")


def _format_spotlight_reasons(entry: SpotlightEntry) -> str:
    return "，".join(signal.reason for signal in entry.signals)


def _format_long_term_reasons(entry: SpotlightEntry) -> str:
    return "，".join(signal.reason for signal in entry.long_term_signals)


def _format_sheet_ranks(entry: SpotlightEntry) -> str:
    return "、".join(f"{label} #{rank}" for label, rank in entry.sheet_ranks)


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
