"""每日早报的内容数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .market_pulse import MarketPulse
from .market_spotlight import MarketSpotlight
from .metric_baseline import MetricAlert
from .project_metrics_trend import ProjectTrendSummary
from .roblox_money_models import RobloxMoneyProjectRevenue


# 早报的组成部分；故障按部分归属，决定发给哪些群。
BriefSection = Literal["market", "project", "money"]


@dataclass(frozen=True)
class BriefFailure:
    """早报某一部分的失败明细；project_id 仅在项目、收入部分的单项目失败时有值。"""

    section: BriefSection
    project_id: str
    label: str
    reason: str


@dataclass(frozen=True)
class MarketSection:
    """行业趋势部分：大盘涨跌、值得关注项目与品类风向。"""

    pulse: MarketPulse | None
    spotlight: MarketSpotlight
    genre_lines: tuple[str, ...]


@dataclass(frozen=True)
class ProjectBriefEntry:
    """自家项目部分的一行；trend 为 None 表示表格里还没有可用数据。"""

    project_id: str
    name: str
    sheet_url: str
    trend: ProjectTrendSummary | None


@dataclass(frozen=True)
class RevenueBriefEntry:
    """收入部分的一行；alert 为日收入相对基线超阈值的提醒。"""

    revenue: RobloxMoneyProjectRevenue
    alert: MetricAlert | None


@dataclass(frozen=True)
class DailyBriefContent:
    """一份早报的全部内容；按群可见范围过滤后再组装卡片。"""

    brief_date: str
    market: MarketSection | None
    projects: tuple[ProjectBriefEntry, ...]
    revenues: tuple[RevenueBriefEntry, ...]
    failures: tuple[BriefFailure, ...]
