from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


DEFAULT_ROBLOX_MONEY_START_DATE = "2026-05-01"
ROBLOX_MONEY_REVENUE_METRIC_CANDIDATES = (
    "Revenue",
    "TotalRevenue",
    "DailyRevenue",
)


@dataclass(frozen=True)
class RobloxMoneyProjectRevenue:
    """表示 Roblox Creator 后台某项目的收入日报摘要。"""

    project_id: str
    project_name: str
    source_url: str
    revenue_metric: str
    report_date: str
    month_start_date: str
    month_end_date: str
    daily_robux: float
    month_to_date_robux: float
    usd_per_100k_robux: float
    fetched_at: str

    @property
    def daily_usd(self) -> float:
        """返回按配置汇率换算后的当日美元收入。"""

        return robux_to_usd(self.daily_robux, self.usd_per_100k_robux)

    @property
    def month_to_date_usd(self) -> float:
        """返回按配置汇率换算后的月累计美元收入。"""

        return robux_to_usd(self.month_to_date_robux, self.usd_per_100k_robux)

    def to_dict(self) -> dict[str, Any]:
        """返回适合序列化写入 JSON/CSV 的字典结构。"""

        payload = asdict(self)
        payload["daily_usd"] = round(self.daily_usd, 2)
        payload["month_to_date_usd"] = round(self.month_to_date_usd, 2)
        return payload


@dataclass(frozen=True)
class RobloxMoneyFetchFailure:
    """描述单个项目收入日报抓取失败的原因。"""

    project_id: str
    project_name: str
    overview_url: str
    reason: str


@dataclass(frozen=True)
class RobloxMoneyReportPayload:
    """聚合收入日报抓取结果，允许部分项目失败。"""

    project_revenues: tuple[RobloxMoneyProjectRevenue, ...]
    failures: tuple[RobloxMoneyFetchFailure, ...]


def robux_to_usd(robux: float, usd_per_100k_robux: float) -> float:
    """按每 100,000 Robux 的美元金额换算收入。"""

    return robux / 100_000 * usd_per_100k_robux


def parse_roblox_money_start_date(raw_value: str) -> date:
    """解析收入日报最早可统计日期。"""

    normalized = raw_value.strip() or DEFAULT_ROBLOX_MONEY_START_DATE
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"ROBLOX_MONEY_START_DATE 不是有效日期: {normalized}") from exc


def parse_usd_per_100k_robux(raw_value: str) -> float:
    """解析 Robux 到美元的换算配置。"""

    normalized = raw_value.strip()
    if not normalized:
        raise ValueError("ROBLOX_MONEY_USD_PER_100K_ROBUX 未配置")
    try:
        value = float(normalized)
    except ValueError as exc:
        raise ValueError(f"ROBLOX_MONEY_USD_PER_100K_ROBUX 不是有效数字: {normalized}") from exc
    if value <= 0:
        raise ValueError("ROBLOX_MONEY_USD_PER_100K_ROBUX 必须大于 0")
    return value
