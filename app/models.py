from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class GameRecord:
    rank: int
    name: str
    universe_id: int | None = None
    place_id: int | None = None
    localized_name: str = ""
    thumbnail_url: str = ""
    creator: str = ""
    playing: int = 0
    visits: int = 0
    up_votes: int = 0
    down_votes: int = 0
    fetched_at: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
