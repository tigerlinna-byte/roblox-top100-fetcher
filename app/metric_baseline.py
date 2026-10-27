"""指标与历史基线对比的通用计算。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .daily_brief_rules import (
    DEFAULT_PROJECT_ALERT_PROFILE,
    PROJECT_ALERT_PROFILE_BY_PROJECT_ID,
    PROJECT_ALERT_THRESHOLDS,
    MetricChangeThreshold,
)


ChangeDirection = Literal["rise", "fall"]


@dataclass(frozen=True)
class MetricAlert:
    """表示一个超过阈值的指标变化。"""

    metric: str
    label: str
    current_text: str
    current_value: float
    baseline_value: float
    change_ratio: float
    direction: ChangeDirection


def average_baseline(values: Iterable[float], *, min_count: int) -> float | None:
    """计算基线均值；有效值不足 min_count 或均值为 0 时返回 None。

    均值为 0 时无法计算相对变化，直接视为“无基线”而不是报无穷大涨幅。
    """

    collected = list(values)
    if len(collected) < min_count:
        return None
    mean = sum(collected) / len(collected)
    if mean == 0:
        return None
    return mean


def evaluate_metric_alert(
    *,
    metric: str,
    label: str,
    current_text: str,
    current_value: float,
    baseline_value: float,
    threshold: MetricChangeThreshold,
) -> MetricAlert | None:
    """判断当前值相对基线是否超过阈值，超过时返回提醒。"""

    change_ratio = current_value / baseline_value - 1
    if threshold.rise_ratio is not None and change_ratio >= threshold.rise_ratio:
        direction: ChangeDirection = "rise"
    elif threshold.fall_ratio is not None and change_ratio <= -threshold.fall_ratio:
        direction = "fall"
    else:
        return None
    return MetricAlert(
        metric=metric,
        label=label,
        current_text=current_text,
        current_value=current_value,
        baseline_value=baseline_value,
        change_ratio=change_ratio,
        direction=direction,
    )


def resolve_project_alert_thresholds(project_id: str) -> dict[str, MetricChangeThreshold]:
    """返回项目当前观测档位对应的阈值表；未人工标记的项目使用默认档位。"""

    profile = PROJECT_ALERT_PROFILE_BY_PROJECT_ID.get(project_id, DEFAULT_PROJECT_ALERT_PROFILE)
    return PROJECT_ALERT_THRESHOLDS[profile]
