from __future__ import annotations

from dataclasses import dataclass

import requests

from .config import Config
from .retry import with_retry


class GitHubClientError(RuntimeError):
    pass


@dataclass
class GitHubClient:
    config: Config
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def upsert_repository_variable(self, name: str, value: str) -> bool:
        if not self._is_configured() or not value:
            return False

        response = self._request(
            "PATCH",
            f"{self._variables_base_url}/{name}",
            json_payload={"name": name, "value": value},
            allow_statuses={204, 404},
        )
        if response.status_code == 204:
            return True

        create_response = self._request(
            "POST",
            self._variables_base_url,
            json_payload={"name": name, "value": value},
            allow_statuses={201},
        )
        return create_response.status_code == 201

    @property
    def _variables_base_url(self) -> str:
        return (
            "https://api.github.com/repos/"
            f"{self.config.github_repo_owner}/{self.config.github_repo_name}/actions/variables"
        )

    def _is_configured(self) -> bool:
        return bool(
            self.config.github_repo_owner
            and self.config.github_repo_name
            and self.config.github_variables_token
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_payload: dict[str, str],
        allow_statuses: set[int],
    ) -> requests.Response:
        def _call() -> requests.Response:
            assert self.session is not None
            response = self.session.request(
                method=method,
                url=url,
                json=json_payload,
                timeout=self.config.request_timeout_seconds,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.config.github_variables_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if response.status_code not in allow_statuses:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}: {response.text[:300]}",
                    response=response,
                )
            return response

        try:
            return with_retry(
                _call,
                attempts=self.config.retry_max_attempts,
                base_backoff_seconds=self.config.retry_backoff_seconds,
                is_retryable=_is_retryable_exception,
            )
        except Exception as exc:  # noqa: BLE001
            raise GitHubClientError(f"GitHub request failed: {url}") from exc


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False
