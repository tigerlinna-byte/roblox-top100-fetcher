from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.config import Config
from app.roblox_client import RobloxClient


class RobloxClientTests(unittest.TestCase):
    def test_parse_basic_tiles(self) -> None:
        response_payload = {
            "games": [
                {
                    "universeId": 101,
                    "rootPlaceId": 1,
                    "name": "A",
                    "playerCount": 99,
                    "totalUpVotes": 10,
                    "totalDownVotes": 1,
                },
                {
                    "universeId": 102,
                    "rootPlaceId": 2,
                    "name": "B",
                    "playerCount": 77,
                    "totalUpVotes": 20,
                    "totalDownVotes": 2,
                },
            ]
        }
        details_payload = {
            "data": [
                {"id": 101, "name": "A", "visits": 1234, "playing": 99, "creator": {"name": "C1"}},
                {"id": 102, "name": "B", "visits": 4567, "playing": 77, "creator": {"name": "C2"}},
            ]
        }

        session = Mock()
        response_a = Mock()
        response_a.status_code = 200
        response_a.json.return_value = response_payload
        response_b = Mock()
        response_b.status_code = 200
        response_b.json.return_value = details_payload
        session.request.side_effect = [response_a, response_b]

        client = RobloxClient(
            config=Config(api_limit=100, roblox_sort_id="top-playing-now"),
            session=session,
        )
        items = client.fetch_top_games()

        self.assertEqual(2, len(items))
        self.assertEqual(1, items[0].rank)
        self.assertEqual(1, items[0].place_id)
        self.assertEqual("A", items[0].name)
        self.assertEqual("C1", items[0].creator)
        self.assertEqual(99, items[0].playing)
        self.assertEqual(1234, items[0].visits)

    def test_respects_api_limit(self) -> None:
        many = [{"universeId": i, "rootPlaceId": i, "name": f"g{i}", "playerCount": i} for i in range(1, 150)]
        session = Mock()
        response_a = Mock()
        response_a.status_code = 200
        response_a.json.return_value = {"games": many}
        response_b = Mock()
        response_b.status_code = 200
        response_b.json.return_value = {"data": []}
        session.request.side_effect = [response_a, response_b]

        client = RobloxClient(
            config=Config(api_limit=10, roblox_sort_id="top-playing-now"),
            session=session,
        )
        items = client.fetch_top_games()
        self.assertEqual(10, len(items))
        self.assertEqual(10, items[-1].rank)


if __name__ == "__main__":
    unittest.main()
