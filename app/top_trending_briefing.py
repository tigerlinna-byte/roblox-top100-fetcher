from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .models import GameRecord


NEW_RELEASE_WINDOW_DAYS = 90
SHEET_LABELS = {
    "top_trending_v4": "热门榜",
    "up_and_coming_v4": "新秀榜",
    "top_playing_now": "在玩榜",
}
SHEET_ORDER = tuple(SHEET_LABELS.keys())


@dataclass(frozen=True)
class TrendingBriefingEntry:
    """表示一条需要出现在 Top100 简报中的重点游戏。"""

    place_id: int
    name: str
    ccu: int
    launch_date: date
    sheet_labels: tuple[str, ...]
    best_rank: int


def build_top_trending_briefing_markdown(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
    spreadsheet_url: str,
) -> str:
    """构建 Top100 飞书消息简报。

    简报只关注“新上榜且首次上线在 3 个月以内”的游戏，并在末尾附完整榜单链接。
    """

    entries = collect_top_trending_briefing_entries(records_by_sheet, previous_ranks_by_sheet)
    lines = ["## 今日关注", ""]

    if entries:
        lines.append("以下游戏为新上榜且首次上线未满 3 个月，建议优先关注：")
        lines.append("")
        for entry in entries:
            lines.append(
                f"- {entry.name}｜{'、'.join(entry.sheet_labels)}｜CCU {entry.ccu:,}｜首次上线 {entry.launch_date.isoformat()}"
            )
    else:
        lines.append("今天没有发现新上榜且首次上线未满 3 个月的重点游戏。")

    lines.extend(["", f"[查看完整榜单]({spreadsheet_url})"])
    return "\n".join(lines)


def collect_top_trending_briefing_entries(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> list[TrendingBriefingEntry]:
    """收集需要进入 Top100 简报的重点游戏。"""

    reference_date = _resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return []

    aggregated: dict[int, dict[str, object]] = {}
    launch_deadline = reference_date - timedelta(days=NEW_RELEASE_WINDOW_DAYS)

    for sheet_title in SHEET_ORDER:
        records = records_by_sheet.get(sheet_title, [])
        previous_ranks = previous_ranks_by_sheet.get(sheet_title, {})
        for record in records:
            if record.place_id is None:
                continue

            launch_date = _resolve_launch_date(record)
            if launch_date is None or launch_date < launch_deadline:
                continue

            is_new_to_sheet = record.place_id not in previous_ranks
            aggregated_entry = aggregated.setdefault(
                record.place_id,
                {
                    "record": record,
                    "launch_date": launch_date,
                    "labels": set(),
                    "new_labels": set(),
                    "best_rank": record.rank,
                },
            )
            aggregated_entry["record"] = _prefer_better_rank_record(
                aggregated_entry["record"],
                record,
            )
            aggregated_entry["launch_date"] = min(
                aggregated_entry["launch_date"],
                launch_date,
            )
            aggregated_entry["best_rank"] = min(aggregated_entry["best_rank"], record.rank)
            aggregated_entry["labels"].add(SHEET_LABELS[sheet_title])
            if is_new_to_sheet:
                aggregated_entry["new_labels"].add(SHEET_LABELS[sheet_title])

    entries: list[TrendingBriefingEntry] = []
    for place_id, payload in aggregated.items():
        if not payload["new_labels"]:
            continue

        labels = tuple(
            label
            for key in SHEET_ORDER
            for label in (SHEET_LABELS[key],)
            if label in payload["labels"]
        )
        record = payload["record"]
        entries.append(
            TrendingBriefingEntry(
                place_id=place_id,
                name=record.localized_name.strip() or record.name,
                ccu=record.playing,
                launch_date=payload["launch_date"],
                sheet_labels=labels,
                best_rank=payload["best_rank"],
            )
        )

    entries.sort(key=lambda item: (item.best_rank, item.name.casefold()))
    return entries


def _resolve_reference_date(records_by_sheet: dict[str, list[GameRecord]]) -> date | None:
    latest_date: date | None = None
    for records in records_by_sheet.values():
        for record in records:
            parsed = _parse_iso_date(record.fetched_at)
            if parsed is None:
                continue
            latest_date = parsed if latest_date is None else max(latest_date, parsed)
    return latest_date


def _resolve_launch_date(record: GameRecord) -> date | None:
    for raw in (record.created_at, record.updated_at, record.fetched_at):
        parsed = _parse_iso_date(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_iso_date(raw: str) -> date | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def _prefer_better_rank_record(current: GameRecord, candidate: GameRecord) -> GameRecord:
    if candidate.rank < current.rank:
        return candidate
    return current
