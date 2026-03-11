from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
import shutil

from app.models import GameRecord
from app.storage import write_outputs


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
        self.assertEqual("https://t1.example/game-a.png", payload[0]["thumbnail_url"])
        self.assertEqual("2026-01-01T00:00:00Z", payload[0]["created_at"])

        with Path(csv_path).open("r", newline="", encoding="utf-8") as fp:
            rows = list(csv.DictReader(fp))

        self.assertEqual(1, len(rows))
        self.assertEqual("https://t1.example/game-a.png", rows[0]["thumbnail_url"])
        self.assertEqual("2026-01-01T00:00:00Z", rows[0]["created_at"])


if __name__ == "__main__":
    unittest.main()
