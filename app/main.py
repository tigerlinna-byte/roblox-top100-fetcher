from __future__ import annotations

import logging
import sys
import time

from .config import Config, load_config
from .feishu_client import FeishuClient, FeishuClientError
from .github_client import GitHubClient, GitHubClientError
from .roblox_client import RobloxClient, RobloxClientError
from .storage import write_outputs
from .summary import build_failure_markdown, build_success_markdown
from .top_trending_sheet import (
    calculate_game_name_width,
    SheetTarget,
    SpreadsheetTarget,
    build_default_sheet_specs,
    build_top_trending_values,
    get_saved_spreadsheet_target,
    get_previous_ranks,
    save_previous_ranks,
    save_spreadsheet_target,
)


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
        client = RobloxClient(cfg)
        report_payload = _fetch_report_payload(cfg, client)
        json_path, csv_path = _write_report_outputs(cfg, report_payload)
    except RobloxClientError:
        logging.exception("Fetch failed.")
        _notify_failure(cfg, "抓取Roblox排行榜失败")
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
        _notify_failure(cfg, "飞书机器人通知失败")
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


def _fetch_report_payload(cfg: Config, client: RobloxClient):
    if cfg.run_report_mode == "top_trending_sheet":
        return {
            "top_trending_v4": client.fetch_games_by_sort_id("Top_Trending_V4"),
            "up_and_coming_v4": client.fetch_games_by_sort_id("Up_And_Coming_V4"),
            "ccu_based_v1": client.fetch_games_by_sort_id("CCU_Based_V1"),
        }
    return client.fetch_top_games()


def _notify_success(cfg: Config, report_payload) -> None:
    feishu_client = FeishuClient(cfg)
    if cfg.run_report_mode == "top_trending_sheet":
        target = _sync_top_trending_sheet(cfg, report_payload, feishu_client)
        feishu_client.send_group_markdown(target.url)
        return

    feishu_client.send_group_markdown(build_success_markdown(cfg, report_payload))


def _sync_top_trending_sheet(
    cfg: Config,
    records_by_sheet,
    feishu_client: FeishuClient,
) -> SpreadsheetTarget:
    previous_ranks = get_previous_ranks(cfg)
    github_client = GitHubClient(cfg)
    target = get_saved_spreadsheet_target(cfg)
    if target is None:
        spreadsheet = feishu_client.create_spreadsheet(cfg.feishu_top_trending_spreadsheet_title)
        sheet_specs = build_default_sheet_specs()
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
        if not save_spreadsheet_target(github_client, target):
            logging.warning("Top Trending spreadsheet identifiers were not persisted.")

    feishu_client.delete_extra_sheets(
        target.spreadsheet_token,
        keep_sheet_ids={sheet.sheet_id for sheet in target.sheets},
    )
    _apply_trending_sheet_presentation(cfg, feishu_client, target, records_by_sheet)

    for sheet in target.sheets:
        sheet_records = records_by_sheet.get(sheet.title, [])
        feishu_client.write_sheet_values(
            target.spreadsheet_token,
            sheet.sheet_id,
            build_top_trending_values(
                cfg,
                sheet.title,
                sheet_records,
                previous_ranks.get(sheet.title, {}),
            ),
        )
        if not save_previous_ranks(github_client, sheet, sheet_records):
            logging.warning("Previous ranks were not persisted for %s.", sheet.title)
    return target


def _apply_trending_sheet_presentation(cfg, feishu_client, target, records_by_sheet) -> None:
    try:
        feishu_client.update_spreadsheet_title(
            target.spreadsheet_token,
            cfg.feishu_top_trending_spreadsheet_title,
        )
    except FeishuClientError:
        logging.warning("Failed to update spreadsheet title.", exc_info=True)

    for sheet in target.sheets:
        try:
            feishu_client.apply_sheet_layout(
                target.spreadsheet_token,
                sheet.sheet_id,
                rank_width=60,
                game_name_width=350,
                developer_width=150,
            )
        except FeishuClientError:
            logging.warning("Failed to apply sheet layout for %s.", sheet.title, exc_info=True)


def _output_prefix(cfg: Config) -> str:
    if cfg.run_report_mode == "top_trending_sheet":
        return "top_trending"
    return "top100"


def _write_report_outputs(cfg: Config, report_payload):
    if cfg.run_report_mode == "top_trending_sheet":
        return write_outputs(
            cfg.output_dir,
            report_payload["top_trending_v4"],
            prefix=_output_prefix(cfg),
        )
    return write_outputs(
        cfg.output_dir,
        report_payload,
        prefix=_output_prefix(cfg),
    )


if __name__ == "__main__":
    sys.exit(run_once())
