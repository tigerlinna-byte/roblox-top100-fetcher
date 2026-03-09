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

    def test_fetch_top_trending_discovers_sort_by_name(self) -> None:
        session = Mock()

        sorts_response = Mock()
        sorts_response.status_code = 200
        sorts_response.json.return_value = {
            "sorts": [
                {"id": "top-playing-now", "name": "Top Playing Now"},
                {"id": "top-trending", "name": "Top Trending"},
            ]
        }

        games_response = Mock()
        games_response.status_code = 200
        games_response.json.return_value = {
            "games": [
                {
                    "universeId": 101,
                    "rootPlaceId": 1,
                    "name": "Trending A",
                    "playerCount": 99,
                }
            ]
        }

        details_response = Mock()
        details_response.status_code = 200
        details_response.json.return_value = {
            "data": [
                {
                    "id": 101,
                    "name": "Trending A",
                    "visits": 1234,
                    "playing": 99,
                    "creator": {"name": "Studio"},
                    "updated": "2026-03-09T00:00:00Z",
                }
            ]
        }

        session.request.side_effect = [sorts_response, games_response, details_response]

        client = RobloxClient(
            config=Config(api_limit=100, roblox_sort_id=""),
            session=session,
        )

        items = client.fetch_top_trending_games()

        self.assertEqual(1, len(items))
        self.assertEqual("Trending A", items[0].name)
        self.assertEqual("2026-03-09T00:00:00Z", items[0].updated_at)

    def test_fetch_top_trending_falls_back_to_candidate_sort_id(self) -> None:
        session = Mock()

        sorts_response = Mock()
        sorts_response.status_code = 200
        sorts_response.json.return_value = {
            "sorts": [
                {"id": "top-playing-now", "name": "Top Playing Now"},
            ]
        }

        games_response = Mock()
        games_response.status_code = 200
        games_response.json.return_value = {
            "games": [
                {
                    "universeId": 201,
                    "rootPlaceId": 11,
                    "name": "Trending B",
                    "playerCount": 55,
                }
            ]
        }

        details_response = Mock()
        details_response.status_code = 200
        details_response.json.return_value = {
            "data": [
                {
                    "id": 201,
                    "name": "Trending B",
                    "visits": 8888,
                    "playing": 55,
                    "creator": {"name": "Studio B"},
                }
            ]
        }

        session.request.side_effect = [sorts_response, games_response, details_response]

        client = RobloxClient(
            config=Config(api_limit=100, roblox_sort_id=""),
            session=session,
        )

        items = client.fetch_top_trending_games()

        self.assertEqual(1, len(items))
        self.assertEqual("Trending B", items[0].name)
        sort_request = session.request.call_args_list[1].kwargs
        self.assertEqual("top-trending", sort_request["params"]["sortId"])


if __name__ == "__main__":
    unittest.main()
