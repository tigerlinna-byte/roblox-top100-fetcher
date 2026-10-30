from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
import logging
import sys
import time

from .config import SCHEDULED_TRIGGER_SOURCE, Config, load_config
from .daily_brief_audience import BriefAudience, filter_brief_for_audience, resolve_brief_audiences
from .daily_brief_card import build_daily_brief_card, strip_project_title
from .daily_brief_models import (
    BriefFailure,
    DailyBriefContent,
    MarketSection,
    ProjectBriefEntry,
    RevenueBriefEntry,
)
from .daily_brief_rules import (
    MARKET_PULSE_SHEET_KEY,
    PROJECT_TREND_BASELINE_DAYS,
    PROJECT_TREND_MIN_BASELINE_DAYS,
    REVENUE_ALERT_METRIC,
    REVENUE_ALERT_METRIC_LABEL,
)
from .feishu_client import FeishuClient, FeishuClientError
from .game_trend_history import (
    GameDailySnapshot,
    GameTrendHistory,
    build_game_daily_snapshots,
    merge_game_trend_history,
    parse_game_trend_history,
    serialize_game_trend_history,
)
from .github_client import GitHubClient, GitHubClientError
from .market_pulse import (
    MARKET_CCU_HISTORY_VAR,
    MarketPulse,
    build_market_ccu_snapshot,
    build_market_pulse,
    merge_market_ccu_history,
    parse_market_ccu_history,
    serialize_market_ccu_history,
)
from .market_spotlight import build_genre_wind_lines, build_market_spotlight
from .metric_baseline import (
    MetricAlert,
    average_baseline,
    evaluate_metric_alert,
    resolve_project_alert_thresholds,
)
from .models import GameRecord
from .project_metrics_models import ProjectDailyMetricsRecord, now_iso
from .project_metrics_trend import build_project_trend_summary
from .project_metrics_sheet import (
    PROJECT_METRICS_3_SPREADSHEET_TOKEN_VAR,
    PROJECT_METRICS_4_SPREADSHEET_TOKEN_VAR,
    PROJECT_METRICS_5_SPREADSHEET_TOKEN_VAR,
    PROJECT_METRICS_SPREADSHEET_TOKEN_VAR,
    ProjectMetricsSheetVariables,
    ProjectMetricsSpreadsheetTarget,
    build_project_metrics_query_plan,
    build_project_metrics_rank_color_cells,
    build_project_metrics_rebuild_rows,
    get_project_metrics_end_column_letter,
    get_saved_project_metrics_target,
    resolve_project_metrics_column_insert_range,
    resolve_project_metrics_variables,
    save_project_metrics_target,
)
from .roblox_money_models import (
    RobloxMoneyFetchFailure,
    RobloxMoneyProjectRevenue,
    RobloxMoneyReportPayload,
    parse_roblox_money_start_date,
    parse_usd_per_100k_robux,
)
from .roblox_money_summary import build_roblox_money_card, format_robux
from .roblox_client import RobloxClient, RobloxClientError
from .roblox_creator_metrics_client import (
    RobloxCreatorAuthenticationError,
    RobloxCreatorMetricsClient,
    RobloxCreatorMetricsClientError,
    resolve_project_metrics_query_date_bounds,
)
from .storage import (
    write_json_document,
    write_json_output,
    write_outputs,
    write_project_metrics_output,
    write_roblox_money_output,
)
from .summary import (
    build_failure_markdown,
    build_project_metrics_partial_failure_markdown,
    resolve_local_today,
)
from .top_trending_briefing import build_top_trending_briefing_card
from .top_trending_sheet import (
    build_game_name_highlight_cells,
    SheetTarget,
    SpreadsheetTarget,
    build_default_sheet_specs,
    build_launch_date_cells,
    build_rank_change_cells,
    build_thumbnail_cells,
    build_top_trending_values,
    get_previous_ranks,
    get_recent_place_ids_by_sheet,
    get_saved_spreadsheet_target,
    resolve_spreadsheet_variables,
    save_previous_ranks,
    save_spreadsheet_target,
)


PROJECT_METRICS_REPORT_MODE = "roblox_project_daily_metrics"
ROBLOX_MONEY_REPORT_MODE = "roblox_money"
# 每日早报：一次运行汇总行业趋势、自家项目与收入。
DAILY_BRIEF_REPORT_MODE = "daily_brief"
# 早报卡片落盘文件前缀，便于在 artifacts 中查看各群实际收到的内容。
DAILY_BRIEF_CARDS_OUTPUT_PREFIX = "daily_brief_cards"
# 值得关注打分明细落盘文件前缀，包含爆发分、长线分及其依据，便于调整阈值。
DAILY_BRIEF_SPOTLIGHT_OUTPUT_PREFIX = "daily_brief_spotlight"
# 早报各部分整体失败时，在“数据异常”中展示的名称。
MARKET_SECTION_LABEL = "行业趋势"
PROJECT_SECTION_LABEL = "自家项目"
MONEY_SECTION_LABEL = "收入"
PROJECT_METRICS_SHEET_MAX_ROWS = 365
PROJECT_METRICS_SHEET_END_COLUMN = get_project_metrics_end_column_letter()
# 以下项目的日报信息仅发送到现有全量群（test 群）名单。
FULL_GROUP_ONLY_PROJECT_IDS = frozenset({"10304101434", "10403337696"})
# Top Earning 今日关注需要覆盖前 300 名，用于发现收入榜新上榜游戏。
TOP_EARNING_FETCH_LIMIT = 300


@dataclass(frozen=True)
class ProjectMetricsFetchFailure:
    """描述单个项目日报抓取失败的原因。"""

    project_id: str
    overview_url: str
    reason: str


@dataclass(frozen=True)
class ProjectMetricsReportPayload:
    """聚合项目日报抓取结果，允许部分项目失败。"""

    records_by_project_id: dict[str, list[ProjectDailyMetricsRecord]]
    failures: tuple[ProjectMetricsFetchFailure, ...]


@dataclass(frozen=True)
class DailyBriefFetchPayload:
    """早报三部分的原始抓取结果；某部分为 None 时，对应的 *_failure 记录失败原因。"""

    records_by_sheet: dict[str, list[GameRecord]] | None
    market_failure: str
    project_metrics: ProjectMetricsReportPayload | None
    project_failure: str
    money: RobloxMoneyReportPayload | None
    money_failure: str


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )



def run_once() -> int:
    configure_logging()
    cfg = load_config()
    logging.info("Starting Roblox sync in mode %s.", cfg.run_report_mode)
    start = time.time()

    try:
        report_payload = _fetch_report_payload(cfg)
        json_path, csv_path = _write_report_outputs(cfg, report_payload)
    except (RobloxClientError, RobloxCreatorMetricsClientError) as exc:
        logging.exception("Fetch failed.")
        _notify_failure(cfg, _resolve_fetch_failure_reason(cfg, exc))
        return 1
    except Exception:  # noqa: BLE001
        logging.exception("Unexpected error.")
        _notify_failure(cfg, "任务出现未预期异常")
        return 1

    elapsed = time.time() - start
    logging.info("Fetched report payload in %.2fs", elapsed)
    logging.info("JSON saved: %s", json_path)
    if csv_path is not None:
        logging.info("CSV saved:  %s", csv_path)
    try:
        _notify_success(cfg, report_payload)
    except FeishuClientError:
        logging.exception("Feishu notify failed.")
        _notify_failure(cfg, _resolve_feishu_failure_reason(cfg))
        return 1
    except GitHubClientError:
        logging.exception("GitHub variable update failed.")
        _notify_failure(cfg, _resolve_github_update_failure_reason(cfg))
        return 1
    except Exception:  # noqa: BLE001
        logging.exception("Unexpected error during Feishu stage.")
        _notify_failure(cfg, "飞书通知阶段出现未预期异常")
        return 1

    return 0



def _notify_failure(cfg: Config, reason: str) -> None:
    try:
        FeishuClient(cfg).send_group_markdown(build_failure_markdown(cfg, reason))
    except Exception:  # noqa: BLE001
        logging.exception("Failed to send failure notification.")



def _fetch_report_payload(cfg: Config):
    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        return _fetch_daily_brief_payload(cfg)

    if cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        return _fetch_roblox_money_payload(cfg)

    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return _fetch_project_metrics_payload(cfg)

    if cfg.run_report_mode == "top_trending_sheet":
        return _fetch_top_trending_records(cfg)
    return RobloxClient(cfg).fetch_top_games()


def _fetch_top_trending_records(cfg: Config) -> dict[str, list[GameRecord]]:
    """抓取今日关注所需的各榜单；收入榜失败时跳过，不影响其余榜单。"""

    client = RobloxClient(cfg)
    records_by_sheet = {
        "top_trending_v4": client.fetch_games_by_sort_id(
            "Top_Trending_V4",
            include_thumbnails=False,
        ),
        "up_and_coming_v4": client.fetch_games_by_sort_id(
            "Up_And_Coming_V4",
            include_thumbnails=False,
        ),
        "top_playing_now": client.fetch_games_by_sort_id(
            "top-playing-now",
            include_thumbnails=False,
        ),
    }
    try:
        records_by_sheet["top_earning"] = client.fetch_top_earning_games(
            limit=TOP_EARNING_FETCH_LIMIT,
            include_thumbnails=False,
        )
    except RobloxClientError:
        logging.warning(
            "Top Earning fetch failed; skipping top earning briefing input.",
            exc_info=True,
        )
    return records_by_sheet


def _fetch_project_metrics_payload(cfg: Config) -> ProjectMetricsReportPayload:
    """按项目抓取日报指标，允许单项目失败。"""

    variables_list = resolve_project_metrics_variables(cfg)
    if not variables_list:
        raise RobloxCreatorMetricsClientError("未配置任何项目日报 overview 地址")

    client = RobloxCreatorMetricsClient(cfg)
    feishu_client = FeishuClient(cfg)
    records_by_project_id: dict[str, list[ProjectDailyMetricsRecord]] = {}
    failures: list[ProjectMetricsFetchFailure] = []
    # Cookie 由所有项目共用，一旦确认失效就记录下来，后续项目不再向 Roblox 发送注定 401 的请求。
    authentication_error: RobloxCreatorAuthenticationError | None = None
    for variables in variables_list:
        try:
            query_plan = _build_project_metrics_query_plan_for_project(
                cfg,
                feishu_client,
                variables,
            )
            if query_plan and authentication_error is not None:
                failures.append(
                    ProjectMetricsFetchFailure(
                        project_id=variables.project_id,
                        overview_url=variables.overview_url,
                        reason=str(authentication_error),
                    )
                )
            elif query_plan:
                records_by_project_id[variables.project_id] = client.fetch_project_daily_metrics(
                    variables.overview_url,
                    report_dates=query_plan.keys(),
                    requested_fields_by_date=query_plan,
                )
            else:
                records_by_project_id[variables.project_id] = []
                logging.info(
                    "Project metrics for %s are already complete in the tracked sheet window.",
                    variables.project_id,
                )
        except FeishuClientError as exc:
            logging.exception("Failed to inspect project metrics sheet for %s.", variables.project_id)
            failures.append(
                ProjectMetricsFetchFailure(
                    project_id=variables.project_id,
                    overview_url=variables.overview_url,
                    reason=f"读取飞书项目日报表失败: {exc}",
                )
            )
        except RobloxCreatorAuthenticationError as exc:
            logging.error(
                "Roblox creator cookie rejected while fetching project metrics for %s; "
                "remaining projects will skip Roblox requests.",
                variables.project_id,
            )
            authentication_error = exc
            failures.append(
                ProjectMetricsFetchFailure(
                    project_id=variables.project_id,
                    overview_url=variables.overview_url,
                    reason=str(exc),
                )
            )
        except RobloxCreatorMetricsClientError as exc:
            logging.exception("Failed to fetch project metrics for %s.", variables.project_id)
            failures.append(
                ProjectMetricsFetchFailure(
                    project_id=variables.project_id,
                    overview_url=variables.overview_url,
                    reason=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logging.exception(
                "Unexpected error while fetching project metrics for %s.",
                variables.project_id,
            )
            failures.append(
                ProjectMetricsFetchFailure(
                    project_id=variables.project_id,
                    overview_url=variables.overview_url,
                    reason=f"未预期异常: {exc}",
                )
            )

    return ProjectMetricsReportPayload(
        records_by_project_id=records_by_project_id,
        failures=tuple(failures),
    )


def _fetch_daily_brief_payload(cfg: Config) -> DailyBriefFetchPayload:
    """依次抓取早报三部分的原始数据；任一部分失败只记录原因，不影响其余部分。"""

    records_by_sheet: dict[str, list[GameRecord]] | None = None
    market_failure = ""
    try:
        records_by_sheet = _fetch_top_trending_records(cfg)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Daily brief market fetch failed.")
        market_failure = _resolve_fetch_failure_reason(replace(cfg, run_report_mode="top_trending_sheet"), exc)

    project_metrics: ProjectMetricsReportPayload | None = None
    project_failure = ""
    try:
        project_metrics = _fetch_project_metrics_payload(cfg)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Daily brief project metrics fetch failed.")
        project_failure = _resolve_fetch_failure_reason(replace(cfg, run_report_mode=PROJECT_METRICS_REPORT_MODE), exc)

    money: RobloxMoneyReportPayload | None = None
    money_failure = ""
    try:
        money = _fetch_roblox_money_payload(cfg)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Daily brief money fetch failed.")
        money_failure = _resolve_fetch_failure_reason(replace(cfg, run_report_mode=ROBLOX_MONEY_REPORT_MODE), exc)

    return DailyBriefFetchPayload(
        records_by_sheet=records_by_sheet,
        market_failure=market_failure,
        project_metrics=project_metrics,
        project_failure=project_failure,
        money=money,
        money_failure=money_failure,
    )


def _fetch_roblox_money_payload(cfg: Config) -> RobloxMoneyReportPayload:
    """抓取收入日报摘要，允许单项目失败。"""

    variables_list = _resolve_roblox_money_variables(cfg)
    if not variables_list:
        raise RobloxCreatorMetricsClientError("未配置任何 Roblox 收入日报 overview 地址")

    try:
        minimum_start_date = parse_roblox_money_start_date(cfg.roblox_money_start_date)
        usd_per_100k_robux = parse_usd_per_100k_robux(cfg.roblox_money_usd_per_100k_robux)
    except ValueError as exc:
        raise RobloxCreatorMetricsClientError(str(exc)) from exc

    client = RobloxCreatorMetricsClient(cfg)
    project_revenues: list[RobloxMoneyProjectRevenue] = []
    failures: list[RobloxMoneyFetchFailure] = []
    # Cookie 由所有项目共用，一旦确认失效就记录下来，后续项目不再向 Roblox 发送注定 401 的请求。
    authentication_error: RobloxCreatorAuthenticationError | None = None
    for variables in variables_list:
        project_name = variables.spreadsheet_title or f"项目 {variables.project_id}"
        if authentication_error is not None:
            failures.append(
                RobloxMoneyFetchFailure(
                    project_id=variables.project_id,
                    project_name=project_name,
                    overview_url=variables.overview_url,
                    reason=str(authentication_error),
                )
            )
            continue
        try:
            series = client.fetch_project_revenue_series(
                variables.overview_url,
                minimum_start_date=minimum_start_date,
            )
            if not series.values:
                raise RobloxCreatorMetricsClientError("未找到 Roblox 总收入指标数据")
            minimum_start_date_text = minimum_start_date.isoformat()
            available_values = {
                item_date: value
                for item_date, value in series.values.items()
                if item_date >= minimum_start_date_text
            }
            if not available_values:
                raise RobloxCreatorMetricsClientError(
                    f"未找到 {minimum_start_date_text} 之后的 Roblox 总收入指标数据"
                )
            report_date = date.fromisoformat(max(available_values))
            month_start_date = max(minimum_start_date, report_date.replace(day=1))
            report_date_text = report_date.isoformat()
            month_values = {
                item_date: value
                for item_date, value in available_values.items()
                if month_start_date.isoformat() <= item_date <= report_date_text
            }
            project_revenues.append(
                RobloxMoneyProjectRevenue(
                    project_id=variables.project_id,
                    project_name=project_name,
                    source_url=variables.overview_url,
                    revenue_metric=series.metric,
                    report_date=report_date_text,
                    month_start_date=month_start_date.isoformat(),
                    month_end_date=report_date_text,
                    daily_robux=available_values[report_date_text],
                    month_to_date_robux=sum(month_values.values()),
                    usd_per_100k_robux=usd_per_100k_robux,
                    fetched_at=now_iso(),
                    baseline_daily_robux=_collect_revenue_baseline(available_values, report_date),
                )
            )
        except RobloxCreatorAuthenticationError as exc:
            logging.error(
                "Roblox creator cookie rejected while fetching Roblox money for %s; "
                "remaining projects will skip Roblox requests.",
                variables.project_id,
            )
            authentication_error = exc
            failures.append(
                RobloxMoneyFetchFailure(
                    project_id=variables.project_id,
                    project_name=project_name,
                    overview_url=variables.overview_url,
                    reason=str(exc),
                )
            )
        except RobloxCreatorMetricsClientError as exc:
            logging.exception("Failed to fetch Roblox money for %s.", variables.project_id)
            failures.append(
                RobloxMoneyFetchFailure(
                    project_id=variables.project_id,
                    project_name=project_name,
                    overview_url=variables.overview_url,
                    reason=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logging.exception("Unexpected error while fetching Roblox money for %s.", variables.project_id)
            failures.append(
                RobloxMoneyFetchFailure(
                    project_id=variables.project_id,
                    project_name=project_name,
                    overview_url=variables.overview_url,
                    reason=f"未预期异常: {exc}",
                )
            )

    return RobloxMoneyReportPayload(
        project_revenues=tuple(project_revenues),
        failures=tuple(failures),
    )


def _collect_revenue_baseline(daily_values: dict[str, float], report_date: date) -> tuple[float, ...]:
    """取统计日之前基线窗口内已有的日收入，供早报判断收入涨跌。"""

    return tuple(
        daily_values[day]
        for offset in range(1, PROJECT_TREND_BASELINE_DAYS + 1)
        for day in ((report_date - timedelta(days=offset)).isoformat(),)
        if day in daily_values
    )


def _build_project_metrics_query_plan_for_project(
    cfg: Config,
    feishu_client: FeishuClient,
    variables: ProjectMetricsSheetVariables,
) -> dict[date, tuple[str, ...]]:
    """读取项目日报旧表，并生成本次需要向 Roblox 查询的日期和字段。"""

    bounds = resolve_project_metrics_query_date_bounds(
        variables.project_id,
        cfg.feishu_timezone,
    )
    if bounds is None:
        return {}

    existing_rows = _read_project_metrics_existing_rows(cfg, feishu_client, variables)
    start_date, end_date = bounds
    query_plan = build_project_metrics_query_plan(
        existing_rows,
        start_date,
        end_date,
        max_data_rows=PROJECT_METRICS_SHEET_MAX_ROWS - 1,
    )
    query_dates = tuple(query_plan)
    logging.info(
        "Project metrics %s needs %s date(s) from %s to %s.",
        variables.project_id,
        len(query_dates),
        start_date.isoformat(),
        end_date.isoformat(),
    )
    return query_plan


def _read_project_metrics_existing_rows(
    cfg: Config,
    feishu_client: FeishuClient,
    variables: ProjectMetricsSheetVariables,
) -> list[list[object]]:
    """读取已保存项目日报表内容；没有已保存目标时返回空表。"""

    target = get_saved_project_metrics_target(cfg, variables)
    if target is None:
        return []
    return feishu_client.read_sheet_values(
        target.spreadsheet_token,
        target.sheet_id,
        end_column=PROJECT_METRICS_SHEET_END_COLUMN,
        end_row=PROJECT_METRICS_SHEET_MAX_ROWS,
    )



def _notify_success(cfg: Config, report_payload) -> None:
    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        _send_daily_brief(cfg, report_payload)
        return

    if cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        feishu_client = FeishuClient(cfg)
        feishu_client.send_group_card(build_roblox_money_card(cfg, report_payload))
        return

    if cfg.run_report_mode == "top_trending_sheet":
        feishu_client = FeishuClient(cfg)
        recent_place_ids_by_sheet = get_recent_place_ids_by_sheet(cfg)
        _persist_top_trending_previous_ranks(cfg, report_payload)
        feishu_client.send_group_card(
            build_top_trending_briefing_card(
                report_payload,
                recent_place_ids_by_sheet,
            )
        )
        return

    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        reported_project_ids = set(report_payload.records_by_project_id) | {
            failure.project_id for failure in report_payload.failures
        }
        full_group_cfg = (
            _resolve_full_group_notification_config(cfg)
            if reported_project_ids & FULL_GROUP_ONLY_PROJECT_IDS
            else None
        )
        feishu_client = FeishuClient(cfg)
        for variables in resolve_project_metrics_variables(cfg):
            if variables.project_id not in report_payload.records_by_project_id:
                continue
            target = _sync_project_metrics_sheet(
                cfg,
                report_payload.records_by_project_id.get(variables.project_id, []),
                feishu_client,
                variables,
            )
            if variables.project_id in FULL_GROUP_ONLY_PROJECT_IDS:
                if full_group_cfg is not None:
                    FeishuClient(full_group_cfg).send_group_markdown(target.url)
            elif variables.spreadsheet_token_variable_name == PROJECT_METRICS_SPREADSHEET_TOKEN_VAR:
                _send_primary_project_metrics_url(cfg, target.url)
            else:
                feishu_client.send_group_markdown(target.url)
        if report_payload.failures:
            failures = [(failure.project_id, failure.reason) for failure in report_payload.failures]
            if any(project_id in FULL_GROUP_ONLY_PROJECT_IDS for project_id, _ in failures):
                if full_group_cfg is not None:
                    FeishuClient(full_group_cfg).send_group_markdown(
                        build_project_metrics_partial_failure_markdown(full_group_cfg, failures)
                    )
                full_chat_ids = set(_split_csv_values(cfg.project_metrics_primary_project_test_chat_ids))
                limited_chat_ids = tuple(
                    chat_id for chat_id in _split_csv_values(cfg.run_chat_id)
                    if chat_id not in full_chat_ids
                )
                visible_failures = [
                    failure for failure in failures if failure[0] not in FULL_GROUP_ONLY_PROJECT_IDS
                ]
                if limited_chat_ids and visible_failures:
                    limited_cfg = replace(cfg, run_chat_id=",".join(limited_chat_ids))
                    FeishuClient(limited_cfg).send_group_markdown(
                        build_project_metrics_partial_failure_markdown(limited_cfg, visible_failures)
                    )
            else:
                feishu_client.send_group_markdown(
                    build_project_metrics_partial_failure_markdown(cfg, failures)
                )
        return

    logging.info("Top100 report outputs updated; success Feishu notification is disabled.")


def _send_daily_brief(cfg: Config, payload: DailyBriefFetchPayload) -> None:
    """同步项目表格并计算各部分结论，再按受众分别发送早报卡片。"""

    brief_date = resolve_local_today(cfg.feishu_timezone)
    failures: list[BriefFailure] = []
    market = _build_market_section(cfg, payload, brief_date, failures)
    projects = _build_project_brief_entries(cfg, payload, failures)
    below_floor_project_ids = frozenset(
        entry.project_id for entry in projects if entry.trend is not None and entry.trend.below_alert_floor
    )
    revenues = _build_revenue_brief_entries(payload, below_floor_project_ids, failures)
    content = DailyBriefContent(
        brief_date=brief_date.isoformat(),
        market=market,
        projects=projects,
        revenues=revenues,
        failures=tuple(failures),
    )

    restricted_project_ids = _resolve_restricted_project_ids(cfg)
    audiences = resolve_brief_audiences(
        _split_csv_values(cfg.run_chat_id),
        _split_csv_values(cfg.project_metrics_primary_project_test_chat_ids),
    )
    cards_by_audience = {
        audience: build_daily_brief_card(
            cfg,
            filter_brief_for_audience(content, audience, restricted_project_ids),
            show_revenue=audience.is_full_group,
        )
        for audience in audiences
    }
    # 先落盘再发送，发送失败时仍能从 artifacts 查看卡片内容。
    write_json_document(
        cfg.output_dir,
        {
            ("full_group" if audience.is_full_group else "limited_group"): {
                "chat_ids": list(audience.chat_ids),
                "card": card,
            }
            for audience, card in cards_by_audience.items()
        },
        prefix=DAILY_BRIEF_CARDS_OUTPUT_PREFIX,
    )
    for audience, card in cards_by_audience.items():
        FeishuClient(_resolve_brief_audience_config(cfg, audience)).send_group_card(card)


def _resolve_brief_audience_config(cfg: Config, audience: BriefAudience) -> Config:
    """生成受众专用的发送配置；全量群禁止回退到 webhook，避免收入发到未知群。"""

    if not audience.chat_ids:
        return cfg
    if audience.is_full_group:
        return replace(cfg, run_chat_id=",".join(audience.chat_ids), feishu_bot_webhook="")
    return replace(cfg, run_chat_id=",".join(audience.chat_ids))


def _resolve_restricted_project_ids(cfg: Config) -> frozenset[str]:
    """只发全量群的项目：受限项目名单，加上只发全量群的第一项目。"""

    primary_project_ids = {
        variables.project_id
        for variables in resolve_project_metrics_variables(cfg)
        if variables.spreadsheet_token_variable_name == PROJECT_METRICS_SPREADSHEET_TOKEN_VAR
    }
    return FULL_GROUP_ONLY_PROJECT_IDS | primary_project_ids


def _build_market_section(
    cfg: Config,
    payload: DailyBriefFetchPayload,
    brief_date: date,
    failures: list[BriefFailure],
) -> MarketSection | None:
    """计算行业趋势，并保存本次排名供下次判断新上榜与排名飙升。"""

    if payload.records_by_sheet is None:
        failures.append(BriefFailure("market", "", MARKET_SECTION_LABEL, payload.market_failure))
        return None

    records_by_sheet = payload.records_by_sheet
    # 必须在保存本次排名之前读取历史，否则“上次运行”会变成本次自己。
    variables = resolve_spreadsheet_variables(cfg)
    previous_ranks_by_sheet = get_previous_ranks(cfg, variables)
    recent_place_ids_by_sheet = get_recent_place_ids_by_sheet(cfg, variables)
    trend_snapshots = build_game_daily_snapshots(records_by_sheet, brief_date)
    trend_history = _load_game_trend_history(cfg, trend_snapshots, brief_date)
    section = MarketSection(
        pulse=_build_market_pulse(cfg, records_by_sheet, brief_date),
        spotlight=build_market_spotlight(
            records_by_sheet,
            previous_ranks_by_sheet,
            recent_place_ids_by_sheet,
            trend_snapshots,
            trend_history,
        ),
        genre_lines=build_genre_wind_lines(records_by_sheet, recent_place_ids_by_sheet),
    )
    write_json_document(cfg.output_dir, asdict(section.spotlight), prefix=DAILY_BRIEF_SPOTLIGHT_OUTPUT_PREFIX)
    try:
        _persist_top_trending_previous_ranks(cfg, records_by_sheet)
    except GitHubClientError:
        logging.exception("Failed to persist previous ranks for daily brief.")
    return section


def _load_game_trend_history(
    cfg: Config,
    snapshots: dict[int, GameDailySnapshot],
    brief_date: date,
) -> GameTrendHistory:
    """读取游戏每日快照历史；定时任务再把当天快照写回数据分支。

    读取失败时不写入，避免用只有当天的数据覆盖已有历史；写入失败只记录日志，不影响早报发送。
    """

    client = GitHubClient(cfg)
    branch = cfg.game_trend_history_branch
    path = cfg.game_trend_history_path
    try:
        existing = client.get_repository_file(path, branch=branch)
    except GitHubClientError:
        logging.exception("Failed to read game trend history from branch %s; long-term metrics skipped today.", branch)
        return {}
    history = parse_game_trend_history(existing.content if existing else "")
    if cfg.run_trigger_source != SCHEDULED_TRIGGER_SOURCE:
        return history

    history = merge_game_trend_history(history, snapshots, brief_date)
    try:
        if not client.put_repository_file(
            path,
            serialize_game_trend_history(history),
            branch=branch,
            sha=existing.sha if existing else "",
            message=f"chore(data): 更新游戏每日快照 {brief_date.isoformat()}",
        ):
            logging.warning("Game trend history was not persisted: GitHub repository or token is not configured.")
    except GitHubClientError:
        logging.exception(
            "Failed to persist game trend history to branch %s; today's snapshot is lost. "
            "Check that GH_TOKEN has Contents read-and-write permission and the branch exists.",
            branch,
        )
    return history


def _build_market_pulse(
    cfg: Config,
    records_by_sheet: dict[str, list[GameRecord]],
    brief_date: date,
) -> MarketPulse | None:
    """计算大盘涨跌；只有定时任务写入历史，保证每天的快照时间一致、可互相比较。"""

    playing_records = records_by_sheet.get(MARKET_PULSE_SHEET_KEY)
    if not playing_records:
        return None

    snapshot = build_market_ccu_snapshot(playing_records, brief_date)
    history = parse_market_ccu_history(cfg.market_ccu_history)
    if cfg.run_trigger_source == SCHEDULED_TRIGGER_SOURCE:
        history = merge_market_ccu_history(history, snapshot)
        try:
            if not GitHubClient(cfg).upsert_repository_variable(
                MARKET_CCU_HISTORY_VAR,
                serialize_market_ccu_history(history),
            ):
                logging.warning("Market CCU history was not persisted.")
        except GitHubClientError:
            logging.exception("Failed to persist market CCU history.")
    return build_market_pulse(snapshot, history)


def _build_project_brief_entries(
    cfg: Config,
    payload: DailyBriefFetchPayload,
    failures: list[BriefFailure],
) -> tuple[ProjectBriefEntry, ...]:
    """把抓取结果写入各项目表格，再从表格内容计算项目结论。"""

    if payload.project_metrics is None:
        failures.append(BriefFailure("project", "", PROJECT_SECTION_LABEL, payload.project_failure))
        return ()

    variables_list = resolve_project_metrics_variables(cfg)
    names_by_project_id = {
        variables.project_id: strip_project_title(variables.spreadsheet_title) or f"项目 {variables.project_id}"
        for variables in variables_list
    }
    for fetch_failure in payload.project_metrics.failures:
        failures.append(
            BriefFailure(
                "project",
                fetch_failure.project_id,
                names_by_project_id.get(fetch_failure.project_id, f"项目 {fetch_failure.project_id}"),
                fetch_failure.reason,
            )
        )

    feishu_client = FeishuClient(cfg)
    entries: list[ProjectBriefEntry] = []
    for variables in variables_list:
        if variables.project_id not in payload.project_metrics.records_by_project_id:
            continue
        project_name = names_by_project_id[variables.project_id]
        try:
            target, rows = _sync_project_metrics_sheet_rows(
                cfg,
                payload.project_metrics.records_by_project_id[variables.project_id],
                feishu_client,
                variables,
            )
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to sync project metrics sheet for %s.", variables.project_id)
            failures.append(
                BriefFailure("project", variables.project_id, project_name, f"写入飞书项目日报表失败: {exc}")
            )
            continue
        entries.append(
            ProjectBriefEntry(
                project_id=variables.project_id,
                name=project_name,
                sheet_url=target.url,
                trend=build_project_trend_summary(variables.project_id, rows),
            )
        )
    return tuple(entries)


def _build_revenue_brief_entries(
    payload: DailyBriefFetchPayload,
    below_floor_project_ids: frozenset[str],
    failures: list[BriefFailure],
) -> tuple[RevenueBriefEntry, ...]:
    """整理收入部分，并判断日收入相对基线是否超阈值；体量低于提醒门槛的项目不提醒收入涨跌。"""

    if payload.money is None:
        failures.append(BriefFailure("money", "", MONEY_SECTION_LABEL, payload.money_failure))
        return ()

    for fetch_failure in payload.money.failures:
        failures.append(
            BriefFailure(
                "money",
                fetch_failure.project_id,
                f"{strip_project_title(fetch_failure.project_name)} {MONEY_SECTION_LABEL}",
                fetch_failure.reason,
            )
        )
    return tuple(
        RevenueBriefEntry(
            revenue=revenue,
            alert=None if revenue.project_id in below_floor_project_ids else _evaluate_revenue_alert(revenue),
        )
        for revenue in payload.money.project_revenues
    )


def _evaluate_revenue_alert(revenue: RobloxMoneyProjectRevenue) -> MetricAlert | None:
    """日收入与前若干天均值比较，阈值跟随项目观测档位。"""

    baseline = average_baseline(revenue.baseline_daily_robux, min_count=PROJECT_TREND_MIN_BASELINE_DAYS)
    if baseline is None:
        return None
    return evaluate_metric_alert(
        metric=REVENUE_ALERT_METRIC,
        label=REVENUE_ALERT_METRIC_LABEL,
        current_text=format_robux(revenue.daily_robux),
        current_value=revenue.daily_robux,
        baseline_value=baseline,
        threshold=resolve_project_alert_thresholds(revenue.project_id)[REVENUE_ALERT_METRIC],
    )


def _persist_top_trending_previous_ranks(
    cfg: Config,
    records_by_sheet: dict[str, list[GameRecord]],
) -> None:
    """保存 Top Trending 历史排名，供今日关注判断最近 7 天新上榜。"""

    variables = resolve_spreadsheet_variables(cfg)
    github_client = GitHubClient(cfg)
    for _sort_id, title, variable_name, previous_ranks_variable_name in variables.sort_sheets:
        if title not in records_by_sheet:
            logging.warning(
                "Skipping previous rank persistence for %s because its Roblox fetch did not complete.",
                title,
            )
            continue
        sheet = SheetTarget(
            sort_id="",
            title=title,
            variable_name=variable_name,
            previous_ranks_variable_name=previous_ranks_variable_name,
            sheet_id="",
        )
        if not save_previous_ranks(
            github_client,
            sheet,
            records_by_sheet.get(title, []),
            variables.previous_ranks_by_var.get(previous_ranks_variable_name, ""),
        ):
            logging.warning("Previous ranks were not persisted for %s.", title)



def _sync_top_trending_sheet(
    cfg: Config,
    records_by_sheet,
    feishu_client: FeishuClient,
) -> SpreadsheetTarget:
    variables = resolve_spreadsheet_variables(cfg)
    previous_ranks = get_previous_ranks(cfg, variables)
    recent_place_ids_by_sheet = get_recent_place_ids_by_sheet(cfg, variables)
    github_client = GitHubClient(cfg)
    target = get_saved_spreadsheet_target(cfg, variables)
    if target is None:
        spreadsheet = feishu_client.create_spreadsheet(variables.spreadsheet_title)
        sheet_specs = build_default_sheet_specs(variables)
        sheet_titles = [sheet_spec["title"] for sheet_spec in sheet_specs]
        sheet_ids = feishu_client.ensure_sheet_set(
            spreadsheet.spreadsheet_token,
            spreadsheet.sheet_ids[0] if spreadsheet.sheet_ids else None,
            sheet_titles,
        )
        target = SpreadsheetTarget(
            spreadsheet_token=spreadsheet.spreadsheet_token,
            sheets=tuple(
                SheetTarget(
                    sort_id=sheet_spec["sort_id"],
                    title=sheet_spec["title"],
                    variable_name=sheet_spec["variable_name"],
                    previous_ranks_variable_name=sheet_spec["previous_ranks_variable_name"],
                    sheet_id=sheet_id,
                )
                for sheet_spec, sheet_id in zip(sheet_specs, sheet_ids, strict=True)
            ),
            url=spreadsheet.url,
        )
        if not save_spreadsheet_target(github_client, target, variables):
            logging.warning("Top Trending spreadsheet identifiers were not persisted.")

    feishu_client.delete_extra_sheets(
        target.spreadsheet_token,
        keep_sheet_ids={sheet.sheet_id for sheet in target.sheets},
    )
    _apply_trending_sheet_presentation(variables.spreadsheet_title, feishu_client, target)

    for sheet in target.sheets:
        if sheet.title not in records_by_sheet:
            logging.warning("Skipping %s sheet because its Roblox fetch did not complete.", sheet.title)
            continue
        sheet_records = records_by_sheet.get(sheet.title, [])
        previous_sheet_ranks = previous_ranks.get(sheet.title, {})
        values = build_top_trending_values(
            cfg,
            sheet.title,
            sheet_records,
            previous_sheet_ranks,
        )
        feishu_client.write_sheet_values(
            target.spreadsheet_token,
            sheet.sheet_id,
            values,
        )
        feishu_client.reset_sheet_font_colors(
            target.spreadsheet_token,
            sheet.sheet_id,
            row_count=len(values),
        )
        try:
            feishu_client.write_sheet_images(
                target.spreadsheet_token,
                sheet.sheet_id,
                build_thumbnail_cells(sheet_records),
            )
        except FeishuClientError:
            logging.warning("Failed to write sheet images for %s.", sheet.title, exc_info=True)
        feishu_client.apply_rank_change_colors(
            target.spreadsheet_token,
            sheet.sheet_id,
            build_rank_change_cells(sheet_records, previous_sheet_ranks),
        )
        feishu_client.apply_launch_date_colors(
            target.spreadsheet_token,
            sheet.sheet_id,
            build_launch_date_cells(sheet_records),
        )
        feishu_client.apply_game_name_highlight_colors(
            target.spreadsheet_token,
            sheet.sheet_id,
            build_game_name_highlight_cells(
                sheet.title,
                records_by_sheet,
                recent_place_ids_by_sheet,
            ),
        )
        if not save_previous_ranks(
            github_client,
            sheet,
            sheet_records,
            variables.previous_ranks_by_var.get(sheet.previous_ranks_variable_name, ""),
        ):
            logging.warning("Previous ranks were not persisted for %s.", sheet.title)
    return target



def _sync_project_metrics_sheet(
    cfg: Config,
    records: list[ProjectDailyMetricsRecord],
    feishu_client: FeishuClient,
    variables: ProjectMetricsSheetVariables,
) -> ProjectMetricsSpreadsheetTarget:
    """把项目指标写入飞书表格，返回表格目标。"""

    target, _rows = _sync_project_metrics_sheet_rows(cfg, records, feishu_client, variables)
    return target


def _sync_project_metrics_sheet_rows(
    cfg: Config,
    records: list[ProjectDailyMetricsRecord],
    feishu_client: FeishuClient,
    variables: ProjectMetricsSheetVariables,
) -> tuple[ProjectMetricsSpreadsheetTarget, list[list[object]]]:
    """把项目指标写入飞书表格，同时返回写入后的整表内容，供早报计算项目结论。"""

    github_client = GitHubClient(cfg)
    target = get_saved_project_metrics_target(cfg, variables)
    if target is None:
        spreadsheet = feishu_client.create_spreadsheet(variables.spreadsheet_title)
        sheet_ids = feishu_client.ensure_sheet_set(
            spreadsheet.spreadsheet_token,
            spreadsheet.sheet_ids[0] if spreadsheet.sheet_ids else None,
            [variables.sheet_title],
        )
        target = ProjectMetricsSpreadsheetTarget(
            spreadsheet_token=spreadsheet.spreadsheet_token,
            sheet_id=sheet_ids[0],
            url=spreadsheet.url,
        )
        if not save_project_metrics_target(github_client, target, variables):
            logging.warning("Project metrics spreadsheet identifiers were not persisted.")

    feishu_client.delete_extra_sheets(
        target.spreadsheet_token,
        keep_sheet_ids={target.sheet_id},
    )
    existing_rows = feishu_client.read_sheet_values(
        target.spreadsheet_token,
        target.sheet_id,
        end_column=PROJECT_METRICS_SHEET_END_COLUMN,
        end_row=PROJECT_METRICS_SHEET_MAX_ROWS,
    )
    column_insert_range = resolve_project_metrics_column_insert_range(existing_rows)
    if column_insert_range is not None:
        start_index, end_index = column_insert_range
        feishu_client.insert_sheet_columns(
            target.spreadsheet_token,
            target.sheet_id,
            start_index=start_index,
            end_index=end_index,
        )
    _apply_project_metrics_sheet_presentation(variables.spreadsheet_title, feishu_client, target)
    rebuild_rows = build_project_metrics_rebuild_rows(
        existing_rows,
        records,
        total_rows=PROJECT_METRICS_SHEET_MAX_ROWS,
    )
    feishu_client.write_sheet_values(
        target.spreadsheet_token,
        target.sheet_id,
        rebuild_rows,
    )
    feishu_client.reset_project_metrics_rank_font_colors(
        target.spreadsheet_token,
        target.sheet_id,
        row_count=len(rebuild_rows),
    )
    feishu_client.apply_project_metrics_rank_bold(
        target.spreadsheet_token,
        target.sheet_id,
        row_count=len(rebuild_rows),
    )
    feishu_client.apply_project_metrics_rank_font_colors(
        target.spreadsheet_token,
        target.sheet_id,
        build_project_metrics_rank_color_cells(rebuild_rows),
    )
    return target, rebuild_rows



def _resolve_full_group_notification_config(cfg: Config) -> Config | None:
    """仅允许精确投递到已配置的全量群，不回退到全群或固定 webhook。"""

    allowed_chat_ids = set(_split_csv_values(cfg.project_metrics_primary_project_test_chat_ids))
    if not allowed_chat_ids:
        raise FeishuClientError("全量群项目消息分流需要配置 PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS")
    run_chat_ids = _split_csv_values(cfg.run_chat_id)
    if not run_chat_ids:
        raise FeishuClientError("全量群项目消息分流需要配置 RUN_CHAT_ID")
    target_chat_ids = tuple(chat_id for chat_id in run_chat_ids if chat_id in allowed_chat_ids)
    if not target_chat_ids:
        return None
    if not cfg.feishu_app_id or not cfg.feishu_app_secret:
        raise FeishuClientError("全量群项目消息分流需要 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    return replace(cfg, run_chat_id=",".join(target_chat_ids), feishu_bot_webhook="")



def _send_primary_project_metrics_url(cfg: Config, sheet_url: str) -> None:
    """只把第一项目日报链接发送到 test 群；未配置 test 群时保持原行为。"""

    allowed_chat_ids = _split_csv_values(cfg.project_metrics_primary_project_test_chat_ids)
    if not allowed_chat_ids:
        FeishuClient(cfg).send_group_markdown(sheet_url)
        return

    run_chat_ids = _split_csv_values(cfg.run_chat_id)
    allowed_chat_id_set = set(allowed_chat_ids)
    target_chat_ids = tuple(chat_id for chat_id in run_chat_ids if chat_id in allowed_chat_id_set)
    if not target_chat_ids:
        logging.info("Skipping primary project metrics link outside configured test chats.")
        return

    FeishuClient(replace(cfg, run_chat_id=",".join(target_chat_ids))).send_group_markdown(sheet_url)



def _resolve_roblox_money_variables(cfg: Config) -> tuple[ProjectMetricsSheetVariables, ...]:
    """解析收入日报项目，统计第一、第三、第四和第五项目槽位。"""

    variables_list = resolve_project_metrics_variables(cfg)
    enabled_variable_names = {
        PROJECT_METRICS_SPREADSHEET_TOKEN_VAR,
        PROJECT_METRICS_3_SPREADSHEET_TOKEN_VAR,
        PROJECT_METRICS_4_SPREADSHEET_TOKEN_VAR,
        PROJECT_METRICS_5_SPREADSHEET_TOKEN_VAR,
    }
    return tuple(
        variables
        for variables in variables_list
        if variables.spreadsheet_token_variable_name in enabled_variable_names
    )



def _split_csv_values(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())



def _apply_trending_sheet_presentation(spreadsheet_title: str, feishu_client, target) -> None:
    try:
        feishu_client.update_spreadsheet_title(
            target.spreadsheet_token,
            spreadsheet_title,
        )
    except FeishuClientError:
        logging.warning("Failed to update spreadsheet title.", exc_info=True)

    for sheet in target.sheets:
        try:
            feishu_client.apply_sheet_layout(
                target.spreadsheet_token,
                sheet.sheet_id,
                rank_width=60,
                thumbnail_width=160,
                game_name_width=400,
                genre_width=120,
                online_width=90,
                rank_change_width=60,
                developer_width=150,
            )
        except FeishuClientError:
            logging.warning("Failed to apply sheet layout for %s.", sheet.title, exc_info=True)



def _apply_project_metrics_sheet_presentation(spreadsheet_title: str, feishu_client, target) -> None:
    try:
        feishu_client.update_spreadsheet_title(
            target.spreadsheet_token,
            spreadsheet_title,
        )
    except FeishuClientError:
        logging.warning("Failed to update project metrics spreadsheet title.", exc_info=True)

    try:
        feishu_client.set_sheet_column_widths(
            target.spreadsheet_token,
            target.sheet_id,
            [120, 110, 130, 120, 90, 120, 90, 120, 100, 90, 120, 140, 140, 90, 90, 90, 110, 180, 110, 110, 110, 120, 110, 120, 120, 110, 120, 180, 180],
        )
    except FeishuClientError:
        logging.warning("Failed to apply project metrics sheet layout.", exc_info=True)



def _resolve_fetch_failure_reason(cfg: Config, exc: Exception | None = None) -> str:
    """为抓取失败通知补齐尽量具体的原因。"""

    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        base_reason = "抓取每日早报数据失败"
    elif cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        base_reason = "抓取 Roblox 收入数据失败"
    elif cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        base_reason = "抓取 Roblox 项目数据失败"
    else:
        base_reason = "抓取Roblox排行榜失败"
    detail = str(exc).strip() if exc else ""
    if not detail:
        return base_reason
    if detail.startswith(base_reason):
        return detail
    return f"{base_reason}：{detail}"



def _resolve_feishu_failure_reason(cfg: Config) -> str:
    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        return "飞书每日早报发送失败"
    if cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        return "飞书收入日报通知失败"
    if cfg.run_report_mode == "top_trending_sheet":
        return "飞书今日关注通知或历史排名更新失败"
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return "飞书项目日报写入失败"
    return "飞书机器人通知失败"


def _resolve_github_update_failure_reason(cfg: Config) -> str:
    if cfg.run_report_mode == "top_trending_sheet":
        return "更新今日关注历史排名失败"
    return "写入飞书表格配置失败"



def _output_prefix(cfg: Config) -> str:
    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        return "daily_brief"
    if cfg.run_report_mode == "top_trending_sheet":
        return "top_trending"
    if cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        return "roblox_money"
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return "project_metrics"
    return "top100"



def _write_report_outputs(cfg: Config, report_payload):
    if cfg.run_report_mode == DAILY_BRIEF_REPORT_MODE:
        json_path = write_json_document(
            cfg.output_dir,
            _build_daily_brief_fetch_document(report_payload),
            prefix=_output_prefix(cfg),
        )
        return json_path, None
    if cfg.run_report_mode == "top_trending_sheet":
        json_path = write_json_output(
            cfg.output_dir,
            report_payload["top_trending_v4"],
            prefix=_output_prefix(cfg),
        )
        return json_path, None
    if cfg.run_report_mode == ROBLOX_MONEY_REPORT_MODE:
        return write_roblox_money_output(
            cfg.output_dir,
            list(report_payload.project_revenues),
            prefix=_output_prefix(cfg),
        )
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return write_project_metrics_output(
            cfg.output_dir,
            [
                record
                for variables in resolve_project_metrics_variables(cfg)
                for record in report_payload.records_by_project_id.get(variables.project_id, [])
            ],
            prefix=_output_prefix(cfg),
        )
    return write_outputs(
        cfg.output_dir,
        report_payload,
        prefix=_output_prefix(cfg),
    )


def _build_daily_brief_fetch_document(payload: DailyBriefFetchPayload) -> dict[str, object]:
    """把早报原始抓取结果整理成可序列化的文档，便于在 artifacts 中排查。"""

    project_metrics = payload.project_metrics
    money = payload.money
    return {
        "market": {
            sheet_key: [record.to_dict() for record in records]
            for sheet_key, records in (payload.records_by_sheet or {}).items()
        },
        "market_failure": payload.market_failure,
        "project_records": {
            project_id: [record.to_dict() for record in records]
            for project_id, records in (project_metrics.records_by_project_id if project_metrics else {}).items()
        },
        "project_failures": [
            asdict(failure) for failure in (project_metrics.failures if project_metrics else ())
        ],
        "project_failure": payload.project_failure,
        "revenues": [revenue.to_dict() for revenue in (money.project_revenues if money else ())],
        "revenue_failures": [asdict(failure) for failure in (money.failures if money else ())],
        "money_failure": payload.money_failure,
    }


if __name__ == "__main__":
    sys.exit(run_once())
