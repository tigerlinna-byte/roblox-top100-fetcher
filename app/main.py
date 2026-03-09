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
    SpreadsheetTarget,
    build_top_trending_summary,
    build_top_trending_values,
    get_saved_spreadsheet_target,
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
        records = _fetch_records(cfg, client)
        json_path, csv_path = write_outputs(
            cfg.output_dir,
            records,
            prefix=_output_prefix(cfg),
        )
    except RobloxClientError:
        logging.exception("Fetch failed.")
        _notify_failure(cfg, "抓取Roblox排行榜失败")
        return 1
    except Exception:  # noqa: BLE001
        logging.exception("Unexpected error.")
        _notify_failure(cfg, "任务出现未预期异常")
        return 1

    elapsed = time.time() - start
    logging.info("Fetched %s games in %.2fs", len(records), elapsed)
    logging.info("JSON saved: %s", json_path)
    logging.info("CSV saved:  %s", csv_path)
    try:
        _notify_success(cfg, records)
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


def _fetch_records(cfg: Config, client: RobloxClient):
    if cfg.run_report_mode == "top_trending_sheet":
        return client.fetch_top_trending_games()
    return client.fetch_top_games()


def _notify_success(cfg: Config, records) -> None:
    feishu_client = FeishuClient(cfg)
    if cfg.run_report_mode == "top_trending_sheet":
        target = _sync_top_trending_sheet(cfg, records, feishu_client)
        feishu_client.send_group_markdown(
            build_top_trending_summary(cfg, records, target.url)
        )
        return

    feishu_client.send_group_markdown(build_success_markdown(cfg, records))


def _sync_top_trending_sheet(
    cfg: Config,
    records,
    feishu_client: FeishuClient,
) -> SpreadsheetTarget:
    target = get_saved_spreadsheet_target(cfg)
    if target is None:
        spreadsheet = feishu_client.create_spreadsheet(cfg.feishu_top_trending_spreadsheet_title)
        target = SpreadsheetTarget(
            spreadsheet_token=spreadsheet.spreadsheet_token,
            sheet_id=spreadsheet.sheet_id,
            url=spreadsheet.url,
        )
        github_client = GitHubClient(cfg)
        if not save_spreadsheet_target(github_client, target):
            logging.warning("Top Trending spreadsheet identifiers were not persisted.")

    feishu_client.write_sheet_values(
        target.spreadsheet_token,
        target.sheet_id,
        build_top_trending_values(cfg, records),
    )
    return target


def _output_prefix(cfg: Config) -> str:
    if cfg.run_report_mode == "top_trending_sheet":
        return "top_trending"
    return "top100"


if __name__ == "__main__":
    sys.exit(run_once())
