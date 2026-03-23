from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .models import GameRecord


NEW_RELEASE_WINDOW_DAYS = 90
MAX_BRIEFING_ENTRIES = 10
BRIEFING_NAME_COLOR = "blue"
BRIEFING_SHEET_LABEL_COLOR = "red"
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
    genre: str
    ccu: int
    launch_date: date
    sheet_rank_labels: tuple[str, ...]
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
    visible_entries = entries[:MAX_BRIEFING_ENTRIES]
    title = _build_briefing_title(records_by_sheet, heading_prefix="## ")
    lines = [title, ""]

    if visible_entries:
        lines.append("以下游戏为新上榜且首次上线未满 3 个月，建议优先关注：")
        lines.append("")
        for entry in visible_entries:
            lines.append(
                f"- {entry.name}｜{entry.genre or '-'}｜{'、'.join(entry.sheet_rank_labels)}｜CCU {entry.ccu:,}｜首次上线 {entry.launch_date.isoformat()}"
            )
        if len(entries) > MAX_BRIEFING_ENTRIES:
            lines.extend(["", "其余值得关注的游戏请直接查看下方表格。"])
    else:
        lines.append("今天没有发现新上榜且首次上线未满 3 个月的重点游戏。")

    return "\n".join(lines)


def build_top_trending_briefing_card(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> dict[str, object]:
    """构建 Top100 简报飞书卡片。"""

    entries = collect_top_trending_briefing_entries(records_by_sheet, previous_ranks_by_sheet)
    visible_entries = entries[:MAX_BRIEFING_ENTRIES]
    if visible_entries:
        lines = [
            "**以下游戏为新上榜且首次上线未满 3 个月，建议优先关注：**",
            "",
        ]
        for entry in visible_entries:
            lines.append(
                "- "
                f"<font color='{BRIEFING_NAME_COLOR}'>{entry.name}</font>"
                f"｜{entry.genre or '-'}"
                f"｜<font color='{BRIEFING_SHEET_LABEL_COLOR}'>{'、'.join(entry.sheet_rank_labels)}</font>"
                f"｜CCU {entry.ccu:,}"
                f"｜首次上线 {entry.launch_date.isoformat()}"
            )
        if len(entries) > MAX_BRIEFING_ENTRIES:
            lines.extend(["", "其余值得关注的游戏请直接查看下方表格。"])
    else:
        lines = ["今天没有发现新上榜且首次上线未满 3 个月的重点游戏。"]

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": _build_briefing_title(records_by_sheet),
            }
        },
        "elements": [
            {
                "tag": "markdown",
                "content": "\n".join(lines),
            }
        ],
    }


def collect_top_trending_briefing_entries(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> list[TrendingBriefingEntry]:
    """收集需要进入 Top100 简报的重点游戏。"""

    focus_place_ids_by_sheet = collect_top_trending_focus_place_ids_by_sheet(
        records_by_sheet,
        previous_ranks_by_sheet,
    )

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

            is_new_to_sheet = record.place_id in focus_place_ids_by_sheet.get(sheet_title, set())
            aggregated_entry = aggregated.setdefault(
                record.place_id,
                {
                    "record": record,
                    "launch_date": launch_date,
                    "new_labels_by_sheet": {},
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
            if is_new_to_sheet:
                label = SHEET_LABELS[sheet_title]
                current_rank = aggregated_entry["new_labels_by_sheet"].get(label)
                if current_rank is None or record.rank < current_rank:
                    aggregated_entry["new_labels_by_sheet"][label] = record.rank

    entries: list[TrendingBriefingEntry] = []
    for place_id, payload in aggregated.items():
        if not payload["new_labels_by_sheet"]:
            continue

        sheet_rank_labels = tuple(
            f"{label} #{payload['new_labels_by_sheet'][label]}"
            for key in SHEET_ORDER
            for label in (SHEET_LABELS[key],)
            if label in payload["new_labels_by_sheet"]
        )
        record = payload["record"]
        entries.append(
            TrendingBriefingEntry(
                place_id=place_id,
                name=_build_briefing_display_name(record),
                genre=record.genre.strip(),
                ccu=record.playing,
                launch_date=payload["launch_date"],
                sheet_rank_labels=sheet_rank_labels,
                best_rank=payload["best_rank"],
            )
        )

    entries.sort(key=lambda item: (item.best_rank, item.name.casefold()))
    return entries


def collect_top_trending_focus_place_ids_by_sheet(
    records_by_sheet: dict[str, list[GameRecord]],
    previous_ranks_by_sheet: dict[str, dict[int, int]],
) -> dict[str, set[int]]:
    """收集每个榜单中今天刚上榜且需要高亮的游戏。"""

    reference_date = _resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return {}

    launch_deadline = reference_date - timedelta(days=NEW_RELEASE_WINDOW_DAYS)
    focus_place_ids_by_sheet: dict[str, set[int]] = {}

    for sheet_title in SHEET_ORDER:
        previous_ranks = previous_ranks_by_sheet.get(sheet_title, {})
        for record in records_by_sheet.get(sheet_title, []):
            if record.place_id is None:
                continue

            launch_date = _resolve_launch_date(record)
            if launch_date is None or launch_date < launch_deadline:
                continue

            if record.place_id in previous_ranks:
                continue

            focus_place_ids_by_sheet.setdefault(sheet_title, set()).add(record.place_id)

    return focus_place_ids_by_sheet


def _resolve_reference_date(records_by_sheet: dict[str, list[GameRecord]]) -> date | None:
    latest_date: date | None = None
    for records in records_by_sheet.values():
        for record in records:
            parsed = _parse_iso_date(record.fetched_at)
            if parsed is None:
                continue
            latest_date = parsed if latest_date is None else max(latest_date, parsed)
    return latest_date


def _build_briefing_title(
    records_by_sheet: dict[str, list[GameRecord]],
    heading_prefix: str = "",
) -> str:
    """根据榜单抓取日期构建简报标题。"""

    reference_date = _resolve_reference_date(records_by_sheet)
    if reference_date is None:
        return f"{heading_prefix}今日关注"
    return f"{heading_prefix}今日关注（{reference_date.isoformat()}）"


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


def _build_briefing_display_name(record: GameRecord) -> str:
    english_name = record.name.strip()
    localized_name = record.localized_name.strip()
    if english_name and localized_name and english_name != localized_name:
        return f"{english_name} {localized_name}"
    return localized_name or english_name
