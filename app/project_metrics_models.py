from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


PROJECT_START_DATES = {
    "9682356542": "2026-03-09",
    "9707829514": "2026-03-17",
}
DEFAULT_PROJECT_REQUIRED_FIELDS = ("peak_ccu",)
PROJECT_REQUIRED_FIELDS = {
    # 该项目当前在 Roblox analytics 接口中长期缺失 PeakConcurrentPlayers，
    # 继续强制要求会让日报长期处于“部分失败”状态，因此这里放宽为不校验核心字段。
    "9707829514": (),
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


def get_project_required_fields(project_id: str) -> tuple[str, ...]:
    """返回指定项目判定抓取成功所需的核心字段集合。"""

    configured_fields = PROJECT_REQUIRED_FIELDS.get(project_id)
    if configured_fields is None:
        return DEFAULT_PROJECT_REQUIRED_FIELDS
    return configured_fields
