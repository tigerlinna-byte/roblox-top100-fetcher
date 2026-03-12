from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


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
