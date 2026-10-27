from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any


PROJECT_START_DATES = {
    "9682356542": "2026-03-09",
    "10170801715": "2026-05-31",
    "10304101434": "2026-06-18",
    "10403337696": "2026-07-06",
}
DEFAULT_PROJECT_REQUIRED_FIELDS = ("peak_ccu",)
# 按项目放宽核心字段校验：Roblox analytics 对个别项目长期不返回 PeakConcurrentPlayers 时，
# 在此登记该项目实际要求的核心字段（如空元组），避免日报长期处于“部分失败”状态。
# 当前启用的项目都按默认核心字段校验。
PROJECT_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {}
PROJECT_METRICS_FIELD_NAMES = (
    "peak_ccu",
    "average_session_time",
    "average_session_time_rank",
    "day1_retention",
    "day1_retention_rank",
    "day7_retention",
    "day7_retention_rank",
    "arpdau",
    "payer_conversion_rate",
    "payer_conversion_rate_rank",
    "arppu",
    "arppu_rank",
    "qptr",
    "ptr",
    "dptr",
    "five_minute_retention",
    "home_recommendations",
    "home_recommendation_new_users",
    "sponsored_ads_new_users",
    "client_crash_rate",
    "tablet_memory_gb",
    "pc_memory_gb",
    "phone_memory_gb",
    "client_frame_rate",
    "server_crashes",
    "server_memory",
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
    arpdau: str = ""
    payer_conversion_rate: str = ""
    payer_conversion_rate_rank: str = ""
    arppu: str = ""
    arppu_rank: str = ""
    qptr: str = ""
    ptr: str = ""
    dptr: str = ""
    five_minute_retention: str = ""
    home_recommendations: str = ""
    home_recommendation_new_users: str = ""
    sponsored_ads_new_users: str = ""
    client_crash_rate: str = ""
    tablet_memory_gb: str = ""
    pc_memory_gb: str = ""
    phone_memory_gb: str = ""
    client_frame_rate: str = ""
    server_crashes: str = ""
    server_memory: str = ""
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


def get_project_required_fields(project_id: str) -> tuple[str, ...]:
    """返回指定项目判定日报可写入所需的核心字段集合。"""

    configured_fields = PROJECT_REQUIRED_FIELDS.get(project_id)
    if configured_fields is None:
        return DEFAULT_PROJECT_REQUIRED_FIELDS
    return configured_fields
