from __future__ import annotations

import logging
import sys
import time

from .config import Config, load_config
from .feishu_client import FeishuClient, FeishuClientError
from .roblox_client import RobloxClient, RobloxClientError
from .storage import write_outputs
from .summary import build_failure_markdown, build_success_markdown


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_once() -> int:
    configure_logging()
    cfg = load_config()
    logging.info("Starting Roblox top games fetch.")
    start = time.time()

    try:
        client = RobloxClient(cfg)
        records = client.fetch_top_games()
        json_path, csv_path = write_outputs(cfg.output_dir, records)
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
        feishu_client = FeishuClient(cfg)
        feishu_client.send_group_markdown(build_success_markdown(cfg, records))
    except FeishuClientError:
        logging.exception("Feishu notify failed.")
        _notify_failure(cfg, "飞书机器人通知失败")
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


if __name__ == "__main__":
    sys.exit(run_once())
