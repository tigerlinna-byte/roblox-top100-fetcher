"""每日早报的受众划分：哪些群看到哪些内容。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .daily_brief_models import BriefFailure, DailyBriefContent


@dataclass(frozen=True)
class BriefAudience:
    """一组看到相同早报内容的群。

    chat_ids 为空表示没有指定群，走机器人 webhook 默认投递；
    is_full_group 为 True 时能看到全部项目与收入。
    """

    chat_ids: tuple[str, ...]
    is_full_group: bool


def resolve_brief_audiences(run_chat_ids: tuple[str, ...], full_group_chat_ids: tuple[str, ...]) -> tuple[BriefAudience, ...]:
    """把本次投递的群划分为全量群与精简群两类受众。

    只有同时出现在全量群名单里的群才是全量群；未配置全量群名单时全部按精简群处理，
    确保收入等受限数据不会因为配置缺失而外泄。
    """

    if not run_chat_ids:
        return (BriefAudience(chat_ids=(), is_full_group=False),)

    full_group_chat_id_set = set(full_group_chat_ids)
    full_chats = tuple(chat_id for chat_id in run_chat_ids if chat_id in full_group_chat_id_set)
    limited_chats = tuple(chat_id for chat_id in run_chat_ids if chat_id not in full_group_chat_id_set)
    audiences: list[BriefAudience] = []
    if full_chats:
        audiences.append(BriefAudience(chat_ids=full_chats, is_full_group=True))
    if limited_chats:
        audiences.append(BriefAudience(chat_ids=limited_chats, is_full_group=False))
    return tuple(audiences)


def filter_brief_for_audience(
    content: DailyBriefContent,
    audience: BriefAudience,
    restricted_project_ids: frozenset[str],
) -> DailyBriefContent:
    """按受众裁剪早报：精简群看不到受限项目、收入及其故障明细。"""

    if audience.is_full_group:
        return content
    return replace(
        content,
        projects=tuple(entry for entry in content.projects if entry.project_id not in restricted_project_ids),
        revenues=(),
        failures=tuple(
            failure
            for failure in content.failures
            if _is_failure_visible_to_limited_group(failure, restricted_project_ids)
        ),
    )


def _is_failure_visible_to_limited_group(failure: BriefFailure, restricted_project_ids: frozenset[str]) -> bool:
    """故障明细跟随数据可见性：精简群能看到的数据，其故障才发给精简群。"""

    if failure.section == "market":
        return True
    if failure.section == "money":
        return False
    return failure.project_id not in restricted_project_ids
