from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


PROJECT_START_DATES = {
    "9682356542": "2026-03-09",
}
PROJECT_METRICS_FIELD_NAMES = (
    "average_ccu",
    "peak_ccu",
    "average_session_time",
    "day1_retention",
    "day7_retention",
    "payer_conversion_rate",
    "arppu",
    "qptr",
    "five_minute_retention",
    "home_recommendations",
)


@dataclass(frozen=True)
class ProjectDailyMetricsRecord:
    """表示 Roblox Creator 后台某项目单日指标。"""

    report_date: str
    average_ccu: str
    peak_ccu: str
    average_session_time: str
    day1_retention: str
    day7_retention: str
    payer_conversion_rate: str
    arppu: str
    qptr: str
    five_minute_retention: str
    home_recommendations: str
    project_id: str
    source_url: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        """返回适合序列化写入 JSON/CSV 的字典结构。"""

        return asdict(self)


def now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_project_start_date(project_id: str) -> date | None:
    """返回指定项目的业务起始日期。"""

    raw_value = PROJECT_START_DATES.get(project_id, "").strip()
    if not raw_value:
        return None
    return date.fromisoformat(raw_value)
