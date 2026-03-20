from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import GameRecord
from .project_metrics_models import ProjectDailyMetricsRecord


def write_outputs(
    output_dir: str,
    records: list[GameRecord],
    *,
    prefix: str = "top100",
) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = target / f"{prefix}_{date_str}.json"
    csv_path = target / f"{prefix}_{date_str}.csv"

    payload = [asdict(record) for record in records]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "rank",
                "universe_id",
                "place_id",
                "name",
                "localized_name",
                "genre",
                "thumbnail_url",
                "creator",
                "playing",
                "visits",
                "up_votes",
                "down_votes",
                "fetched_at",
                "created_at",
                "updated_at",
            ],
        )
        writer.writeheader()
        for record in payload:
            writer.writerow(record)

    return json_path, csv_path


def write_project_metrics_output(
    output_dir: str,
    records: list[ProjectDailyMetricsRecord],
    *,
    prefix: str = "project_metrics",
) -> tuple[Path, Path]:
    """将项目日报记录输出为 JSON 与 CSV 文件。"""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = target / f"{prefix}_{date_str}.json"
    csv_path = target / f"{prefix}_{date_str}.csv"
    payload = [record.to_dict() for record in records]

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        fieldnames = list(payload[0].keys()) if payload else list(ProjectDailyMetricsRecord(
            report_date="",
            peak_ccu="",
            average_session_time="",
            day1_retention="",
            day7_retention="",
            payer_conversion_rate="",
            arppu="",
            qptr="",
            five_minute_retention="",
            home_recommendations="",
            client_crash_rate="",
            project_id="",
            source_url="",
            fetched_at="",
        ).to_dict().keys())
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload:
            writer.writerow(row)

    return json_path, csv_path
