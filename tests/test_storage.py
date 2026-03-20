from __future__ import annotations

import csv
import json
import shutil
import unittest
from pathlib import Path

from app.models import GameRecord
from app.project_metrics_models import ProjectDailyMetricsRecord
from app.storage import write_outputs, write_project_metrics_output


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".test-output")
        if self.base.exists():
            shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_writes_json_and_csv(self) -> None:
        sample = [
            GameRecord(
                rank=1,
                place_id=123,
                name="Game A",
                localized_name="游戏A",
                genre="Adventure",
                thumbnail_url="https://t1.example/game-a.png",
                creator="Creator A",
                playing=1000,
                visits=50000,
                up_votes=100,
                down_votes=10,
                fetched_at="2026-03-07T00:00:00Z",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-03-01T00:00:00Z",
            )
        ]

        json_path, csv_path = write_outputs(str(self.base), sample)
        self.assertTrue(Path(json_path).exists())
        self.assertTrue(Path(csv_path).exists())

        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        self.assertEqual(1, len(payload))
        self.assertEqual("Game A", payload[0]["name"])
        self.assertEqual("Adventure", payload[0]["genre"])

        with Path(csv_path).open("r", newline="", encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))

        self.assertEqual(1, len(rows))
        self.assertEqual("Adventure", rows[0]["genre"])

    def test_writes_project_metrics_json_and_csv(self) -> None:
        sample = [
            ProjectDailyMetricsRecord(
                report_date="2026-03-12",
                peak_ccu="2,345",
                average_session_time="18m 30s",
                day1_retention="31%",
                day7_retention="12%",
                payer_conversion_rate="2.5%",
                arppu="$8.90",
                qptr="4.2",
                five_minute_retention="40%",
                home_recommendations="98",
                client_crash_rate="0.12%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
            ProjectDailyMetricsRecord(
                report_date="2026-03-11",
                peak_ccu="2,222",
                average_session_time="17m",
                day1_retention="30%",
                day7_retention="11%",
                payer_conversion_rate="2.1%",
                arppu="$8.10",
                qptr="4.0",
                five_minute_retention="39%",
                home_recommendations="90",
                client_crash_rate="0.10%",
                project_id="9682356542",
                source_url="https://create.roblox.com/dashboard/creations/experiences/9682356542/overview",
                fetched_at="2026-03-12T01:02:03Z",
            ),
        ]

        json_path, csv_path = write_project_metrics_output(str(self.base), sample)
        payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
        self.assertEqual(2, len(payload))

        with Path(csv_path).open("r", newline="", encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))

        self.assertEqual(2, len(rows))
        self.assertEqual("4.2", rows[0]["qptr"])


if __name__ == "__main__":
    unittest.main()
