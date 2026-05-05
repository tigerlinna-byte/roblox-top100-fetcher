from __future__ import annotations

from .config import Config
from .roblox_money_models import RobloxMoneyReportPayload
from .summary import _format_now, _format_trigger


MONEY_PROJECT_NAME_COLOR = "blue"
MONEY_DAILY_VALUE_COLOR = "green"
MONEY_MONTH_VALUE_COLOR = "blue"
MONEY_FAILURE_COLOR = "red"


def build_roblox_money_markdown(cfg: Config, payload: RobloxMoneyReportPayload) -> str:
    """构造 Roblox 收入日报飞书文本消息。"""

    title = _build_money_title(payload)
    lines = [
        f"## **{title}**",
        "",
        f"- 时间: {_format_now(cfg.feishu_timezone)} ({cfg.feishu_timezone})",
        f"- 触发: {_format_trigger(cfg)}",
    ]
    if payload.project_revenues:
        lines.extend(["", "## **收入概览**"])
        for revenue in payload.project_revenues:
            lines.extend(
                [
                    f"- **{_color_text(revenue.project_name, MONEY_PROJECT_NAME_COLOR)}**",
                    (
                        f"  - 当日收入（{revenue.report_date}）: "
                        f"**{_color_text(_format_usd(revenue.daily_usd), MONEY_DAILY_VALUE_COLOR)}**"
                        f"（{_format_robux(revenue.daily_robux)} Robux）"
                    ),
                    (
                        f"  - 月累计（{revenue.month_start_date} 至 {revenue.month_end_date}）: "
                        f"**{_color_text(_format_usd(revenue.month_to_date_usd), MONEY_MONTH_VALUE_COLOR)}**"
                        f"（{_format_robux(revenue.month_to_date_robux)} Robux）"
                    ),
                ]
            )

    if payload.failures:
        lines.extend(["", "## **抓取异常**"])
        for failure in payload.failures:
            project_label = failure.project_name or f"项目 {failure.project_id or '-'}"
            lines.append(
                f"- **{_color_text(project_label, MONEY_FAILURE_COLOR)}**: "
                f"{_color_text(failure.reason, MONEY_FAILURE_COLOR)}"
            )

    if not payload.project_revenues and not payload.failures:
        lines.extend(["", "没有可发送的收入数据。"])

    return "\n".join(lines)


def _build_money_title(payload: RobloxMoneyReportPayload) -> str:
    report_dates = {item.report_date for item in payload.project_revenues if item.report_date}
    if len(report_dates) == 1:
        return f"Roblox 收入日报（{next(iter(report_dates))}）"
    return "Roblox 收入日报"


def _format_usd(value: float) -> str:
    return f"${value:,.2f}"


def _format_robux(value: float) -> str:
    return f"{int(round(value)):,}"


def _color_text(value: str, color: str) -> str:
    return f"<font color='{color}'>{value}</font>"
