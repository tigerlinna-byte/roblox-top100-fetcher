from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
import time

from .config import Config, load_config
from .feishu_client import FeishuClient, FeishuClientError
from .github_client import GitHubClient, GitHubClientError
from .project_metrics_models import ProjectDailyMetricsRecord
from .project_metrics_sheet import (
    ProjectMetricsSheetVariables,
    ProjectMetricsSpreadsheetTarget,
    build_project_metrics_rank_color_cells,
    build_project_metrics_rebuild_rows,
    get_saved_project_metrics_target,
    resolve_project_metrics_variables,
    save_project_metrics_target,
)
from .roblox_client import RobloxClient, RobloxClientError
from .roblox_creator_metrics_client import (
    RobloxCreatorMetricsClient,
    RobloxCreatorMetricsClientError,
)
from .storage import write_outputs, write_project_metrics_output
from .summary import (
    build_failure_markdown,
    build_project_metrics_partial_failure_markdown,
    build_success_markdown,
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
PROJECT_METRICS_SHEET_MAX_ROWS = 365
PROJECT_METRICS_SHEET_END_COLUMN = "V"


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
    logging.info("CSV saved:  %s", csv_path)
    try:
        _notify_success(cfg, report_payload)
    except FeishuClientError:
        logging.exception("Feishu notify failed.")
        _notify_failure(cfg, _resolve_feishu_failure_reason(cfg))
        return 1
    except GitHubClientError:
        logging.exception("GitHub variable update failed.")
        _notify_failure(cfg, "写入飞书表格配置失败")
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
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        variables_list = resolve_project_metrics_variables(cfg)
        if not variables_list:
            raise RobloxCreatorMetricsClientError("未配置任何项目日报 overview 地址")

        client = RobloxCreatorMetricsClient(cfg)
        records_by_project_id: dict[str, list[ProjectDailyMetricsRecord]] = {}
        failures: list[ProjectMetricsFetchFailure] = []
        for variables in variables_list:
            try:
                records_by_project_id[variables.project_id] = client.fetch_project_daily_metrics(
                    variables.overview_url
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

        if not records_by_project_id:
            raise RobloxCreatorMetricsClientError(
                _build_project_metrics_fetch_failure_summary(failures)
            )

        return ProjectMetricsReportPayload(
            records_by_project_id=records_by_project_id,
            failures=tuple(failures),
        )

    client = RobloxClient(cfg)
    if cfg.run_report_mode == "top_trending_sheet":
        return {
            "top_trending_v4": client.fetch_games_by_sort_id("Top_Trending_V4"),
            "up_and_coming_v4": client.fetch_games_by_sort_id("Up_And_Coming_V4"),
            "top_playing_now": client.fetch_games_by_sort_id("top-playing-now"),
        }
    return client.fetch_top_games()



def _notify_success(cfg: Config, report_payload) -> None:
    feishu_client = FeishuClient(cfg)
    if cfg.run_report_mode == "top_trending_sheet":
        recent_place_ids_by_sheet = get_recent_place_ids_by_sheet(cfg)
        target = _sync_top_trending_sheet(cfg, report_payload, feishu_client)
        feishu_client.send_group_card(
            build_top_trending_briefing_card(
                report_payload,
                recent_place_ids_by_sheet,
            )
        )
        feishu_client.send_group_markdown(target.url)
        return

    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        for variables in resolve_project_metrics_variables(cfg):
            if variables.project_id not in report_payload.records_by_project_id:
                continue
            target = _sync_project_metrics_sheet(
                cfg,
                report_payload.records_by_project_id.get(variables.project_id, []),
                feishu_client,
                variables,
            )
            feishu_client.send_group_markdown(target.url)
        if report_payload.failures:
            feishu_client.send_group_markdown(
                build_project_metrics_partial_failure_markdown(
                    cfg,
                    [(failure.project_id, failure.reason) for failure in report_payload.failures],
                )
            )
        return

    feishu_client.send_group_markdown(build_success_markdown(cfg, report_payload))



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
):
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
    _apply_project_metrics_sheet_presentation(variables.spreadsheet_title, feishu_client, target)
    existing_rows = feishu_client.read_sheet_values(
        target.spreadsheet_token,
        target.sheet_id,
        end_column=PROJECT_METRICS_SHEET_END_COLUMN,
        end_row=PROJECT_METRICS_SHEET_MAX_ROWS,
    )
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
    return target



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
            [120, 110, 130, 120, 90, 120, 90, 120, 90, 120, 140, 140, 90, 110, 180, 110, 120, 110, 120, 120, 110, 180],
        )
    except FeishuClientError:
        logging.warning("Failed to apply project metrics sheet layout.", exc_info=True)



def _build_project_metrics_fetch_failure_summary(
    failures: list[ProjectMetricsFetchFailure],
) -> str:
    """汇总全部项目日报抓取失败原因，便于失败通知直出根因。"""

    if not failures:
        return "未获取到任何项目日报数据"
    summary = "；".join(
        f"项目 {failure.project_id}: {failure.reason}" for failure in failures
    )
    return f"全部项目抓取失败：{summary}"


def _resolve_fetch_failure_reason(cfg: Config, exc: Exception | None = None) -> str:
    """为抓取失败通知补齐尽量具体的原因。"""

    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
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
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return "飞书项目日报写入失败"
    return "飞书机器人通知失败"



def _output_prefix(cfg: Config) -> str:
    if cfg.run_report_mode == "top_trending_sheet":
        return "top_trending"
    if cfg.run_report_mode == PROJECT_METRICS_REPORT_MODE:
        return "project_metrics"
    return "top100"



def _write_report_outputs(cfg: Config, report_payload):
    if cfg.run_report_mode == "top_trending_sheet":
        return write_outputs(
            cfg.output_dir,
            report_payload["top_trending_v4"],
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


if __name__ == "__main__":
    sys.exit(run_once())
