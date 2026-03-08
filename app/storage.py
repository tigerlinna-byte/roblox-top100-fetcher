from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .models import GameRecord


def write_outputs(output_dir: str, records: list[GameRecord]) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    json_path = target / f"top100_{date_str}.json"
    csv_path = target / f"top100_{date_str}.csv"

    payload = [asdict(record) for record in records]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(
            fp,
            fieldnames=[
                "rank",
                "place_id",
                "name",
                "creator",
                "playing",
                "visits",
                "up_votes",
                "down_votes",
                "fetched_at",
            ],
        )
        writer.writeheader()
        for record in payload:
            writer.writerow(record)

    return json_path, csv_path
