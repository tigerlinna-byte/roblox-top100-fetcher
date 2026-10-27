"""把早报内容组装成飞书卡片。"""

from __future__ import annotations

from .config import Config
from .daily_brief_models import DailyBriefContent, MarketSection, ProjectBriefEntry, RevenueBriefEntry
from .daily_brief_rules import (
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
STANDOUT_MARK = "⭐"
# CCU 达到一万时改用“万”为单位展示，便于中文阅读。
TEN_THOUSAND = 10_000


def build_daily_brief_card(cfg: Config, content: DailyBriefContent, *, show_revenue: bool) -> dict[str, object]:
    """组装一张早报卡片；show_revenue 只对全量群为 True。"""

    blocks: list[str] = []
    blocks.append(_build_market_block(content.market))
    blocks.append(_build_projects_block(content.projects))
    if show_revenue:
        blocks.append(_build_revenue_block(content.revenues))
    if content.failures:
        blocks.append(_build_failure_block(content))
    blocks.append(
        "\n".join(
            [
                f"时间：{_format_now(cfg.feishu_timezone)}（{cfg.feishu_timezone}）",
                f"触发：{_format_trigger(cfg)}",
            ]
        )
    )

    elements: list[dict[str, object]] = []
    for index, block in enumerate(blocks):
        if index:
            elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": block})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": f"每日早报（{content.brief_date}）"}},
        "elements": elements,
    }


def strip_project_title(title: str) -> str:
    """去掉表格标题里的固定后缀，得到简洁的项目名。"""

    stripped = title.strip()
    for suffix in PROJECT_TITLE_SUFFIXES_TO_STRIP:
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].strip()
    return stripped or title.strip()


def _build_market_block(market: MarketSection | None) -> str:
    lines = ["**行业趋势**"]
    if market is None:
        lines.append("今日榜单数据延迟，详见下方数据异常。")
        return "\n".join(lines)

    lines.extend(_build_pulse_lines(market.pulse))
    lines.extend(f"- 品类风向：{line}" for line in market.genre_lines)
    lines.append("")
    lines.extend(_build_spotlight_lines(market.spotlight))
    return "\n".join(lines)


def _build_pulse_lines(pulse: MarketPulse | None) -> list[str]:
    if pulse is None:
        return []
    snapshot = pulse.snapshot
    broad_label = f"大盘（在玩榜前 {MARKET_PULSE_BROAD_SIZE}"
    if snapshot.game_count < MARKET_PULSE_BROAD_SIZE:
        broad_label += f"，实际 {snapshot.game_count} 款"
    broad_label += "）"
    return [
        f"- {broad_label}：在线 {_format_ccu(snapshot.broad_ccu)}"
        f"{_format_pulse_changes(pulse.broad_day_change, pulse.broad_week_change, pulse.recorded_days)}",
        f"- 头部（前 {MARKET_PULSE_HEAD_SIZE}）：在线 {_format_ccu(snapshot.head_ccu)}"
        f"{_format_pulse_changes(pulse.head_day_change, pulse.head_week_change, pulse.recorded_days)}",
    ]


def _format_pulse_changes(
    day_change: MarketChange | None,
    week_change: MarketChange | None,
    recorded_days: int,
) -> str:
    """有对比数据时展示涨跌，否则提示历史数据仍在积累。"""

    parts: list[str] = []
    if day_change is not None:
        parts.append(f"较昨日 {_format_market_change(day_change)}")
    if week_change is not None:
        parts.append(f"较上周同日 {_format_market_change(week_change)}")
    if not parts:
        return f"｜数据积累中（已记录 {recorded_days} 天）"
    return "｜" + "｜".join(parts)


def _format_market_change(change: MarketChange) -> str:
    ratio_text = _format_ratio(change.change_ratio)
    if change.trend == "up":
        return _color(f"{ratio_text} ↑", RISE_COLOR)
    if change.trend == "down":
        return _color(f"{ratio_text} ↓", FALL_COLOR)
    return f"{ratio_text}（{FLAT_TREND_TEXT}）"


def _build_spotlight_lines(spotlight: MarketSpotlight) -> list[str]:
    if spotlight.standout is None and not spotlight.entries:
        return ["今天没有发现值得特别关注的项目。"]

    lines: list[str] = []
    if spotlight.standout is not None:
        standout = spotlight.standout
        lines.append(
            f"{STANDOUT_MARK} **今日最突出：{_color(standout.name, HIGHLIGHT_NAME_COLOR)}**"
            f"｜{standout.genre or '-'}｜CCU {standout.ccu:,}"
        )
        lines.append(f"  {_format_spotlight_reasons(standout)}｜{_format_sheet_ranks(standout)}")
    if spotlight.entries:
        lines.append("**值得关注**")
        for entry in spotlight.entries:
            lines.append(
                f"- {_color(entry.name, HIGHLIGHT_NAME_COLOR)}｜{entry.genre or '-'}｜CCU {entry.ccu:,}"
                f"｜{_format_spotlight_reasons(entry)}"
            )
    return lines


def _format_spotlight_reasons(entry: SpotlightEntry) -> str:
    return "，".join(signal.reason for signal in entry.signals)


def _format_sheet_ranks(entry: SpotlightEntry) -> str:
    return "、".join(f"{label} #{rank}" for label, rank in entry.sheet_ranks)


def _build_projects_block(projects: tuple[ProjectBriefEntry, ...]) -> str:
    lines = ["**自家项目**"]
    if not projects:
        lines.append("没有可展示的项目数据。")
        return "\n".join(lines)
    for entry in projects:
        lines.append(_build_project_line(entry))
    return "\n".join(lines)


def _build_project_line(entry: ProjectBriefEntry) -> str:
    """有提醒时只列提醒，没有提醒时列核心数字；项目名链接到它的日报表格。"""

    name = f"[{entry.name}]({entry.sheet_url})" if entry.sheet_url else entry.name
    trend = entry.trend
    if trend is None:
        return f"- **{name}**：表格暂无数据"
    if trend.alerts:
        detail = "；".join(_format_alert(alert) for alert in trend.alerts)
    else:
        detail = "｜".join(f"{label} {value}" for label, value in trend.summary_values) or "核心数字未出"
    return f"- **{name}**（{trend.report_date}）：{detail}"


def _build_revenue_block(revenues: tuple[RevenueBriefEntry, ...]) -> str:
    lines = ["**收入**"]
    if not revenues:
        lines.append("没有可展示的收入数据。")
        return "\n".join(lines)
    for entry in revenues:
        revenue = entry.revenue
        line = (
            f"- **{strip_project_title(revenue.project_name)}**（截至 {revenue.report_date}）："
            f"当日 {format_usd(revenue.daily_usd)}（{format_robux(revenue.daily_robux)} Robux）"
            f"｜月累计 {format_usd(revenue.month_to_date_usd)}"
        )
        if entry.alert is not None:
            line += f"｜{_format_alert(entry.alert, include_value=False)}"
        lines.append(line)
    return "\n".join(lines)


def _build_failure_block(content: DailyBriefContent) -> str:
    """同一原因的故障合并成一行，例如 Cookie 失效时不重复列出每个项目。"""

    labels_by_reason: dict[str, list[str]] = {}
    for failure in content.failures:
        labels_by_reason.setdefault(failure.reason, []).append(failure.label)
    lines = ["**数据异常**"]
    for reason, labels in labels_by_reason.items():
        lines.append(f"- {_color('、'.join(labels), FAILURE_COLOR)}：{reason}")
    return "\n".join(lines)


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


def _color(text: str, color: str) -> str:
    return f"<font color='{color}'>{text}</font>"
