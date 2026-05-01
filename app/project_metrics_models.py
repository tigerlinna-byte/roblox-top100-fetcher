from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


PROJECT_START_DATES = {
    "9682356542": "2026-03-09",
    "9707829514": "2026-03-17",
}
PROJECT_METRICS_FIELD_NAMES = (
    "peak_ccu",
    "average_session_time",
    "average_session_time_rank",
    "day1_retention",
    "day1_retention_rank",
    "day7_retention",
    "day7_retention_rank",
    "payer_conversion_rate",
    "payer_conversion_rate_rank",
    "arppu",
    "arppu_rank",
    "qptr",
    "five_minute_retention",
    "home_recommendations",
    "client_crash_rate",
    "tablet_memory_percentage",
    "pc_memory_percentage",
    "phone_memory_percentage",
    "client_frame_rate",
    "server_crashes",
    "server_frame_rate",
)


@dataclass(frozen=True)
class ProjectDailyMetricsRecord:
    """表示 Roblox Creator 后台某项目单日指标。"""

    report_date: str
    peak_ccu: str = ""
    average_session_time: str = ""
    average_session_time_rank: str = ""
    day1_retention: str = ""
    day1_retention_rank: str = ""
    day7_retention: str = ""
    day7_retention_rank: str = ""
    payer_conversion_rate: str = ""
    payer_conversion_rate_rank: str = ""
    arppu: str = ""
    arppu_rank: str = ""
    qptr: str = ""
    five_minute_retention: str = ""
    home_recommendations: str = ""
    client_crash_rate: str = ""
    tablet_memory_percentage: str = ""
    pc_memory_percentage: str = ""
    phone_memory_percentage: str = ""
    client_frame_rate: str = ""
    server_crashes: str = ""
    server_frame_rate: str = ""
    project_id: str = ""
    source_url: str = ""
    fetched_at: str = ""

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
