from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock

from app.config import Config
from app.github_client import GitHubClient, RepositoryFile


def _response(status_code: int, payload: dict[str, object] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload or {}
    return response


class GitHubRepositoryFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = MagicMock()
        cfg = Config(github_repo_owner="owner", github_repo_name="repo", github_variables_token="token")
        self.client = GitHubClient(cfg, session=self.session)

    def test_get_file_decodes_content_from_branch(self) -> None:
        encoded = base64.b64encode('{"games":{}}'.encode("utf-8")).decode("ascii")
        self.session.request.return_value = _response(200, {"content": encoded, "sha": "abc"})

        result = self.client.get_repository_file("history.json", branch="data-history")

        self.assertEqual(RepositoryFile(content='{"games":{}}', sha="abc"), result)
        kwargs = self.session.request.call_args.kwargs
        self.assertEqual("https://api.github.com/repos/owner/repo/contents/history.json", kwargs["url"])
        self.assertEqual({"ref": "data-history"}, kwargs["params"])

    def test_get_missing_file_returns_none(self) -> None:
        self.session.request.return_value = _response(404)

        self.assertIsNone(self.client.get_repository_file("history.json", branch="data-history"))

    def test_put_file_sends_base64_content_with_branch_and_sha(self) -> None:
        self.session.request.return_value = _response(200)

        self.assertTrue(
            self.client.put_repository_file("history.json", "数据", branch="data-history", sha="abc", message="update")
        )

        payload = self.session.request.call_args.kwargs["json"]
        self.assertEqual("PUT", self.session.request.call_args.kwargs["method"])
        self.assertEqual("数据", base64.b64decode(payload["content"]).decode("utf-8"))
        self.assertEqual(("data-history", "abc", "update"), (payload["branch"], payload["sha"], payload["message"]))

    def test_put_new_file_omits_sha(self) -> None:
        self.session.request.return_value = _response(201)

        self.client.put_repository_file("history.json", "{}", branch="data-history", sha="", message="create")

        self.assertNotIn("sha", self.session.request.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
