from __future__ import annotations

import base64
from dataclasses import dataclass

import requests

from .config import Config
from .retry import with_retry


class GitHubClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepositoryFile:
    """仓库中某个文件的内容；sha 用于更新文件时声明基于哪个版本修改。"""

    content: str
    sha: str


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

    def get_repository_file(self, path: str, *, branch: str) -> RepositoryFile | None:
        """读取指定分支上的文件；文件或分支不存在、未配置凭据时返回 None。"""

        if not self._is_configured():
            return None
        response = self._request(
            "GET",
            f"{self._contents_base_url}/{path}",
            params={"ref": branch},
            allow_statuses={200, 404},
        )
        if response.status_code == 404:
            return None
        payload = response.json()
        content = base64.b64decode(payload.get("content", "")).decode("utf-8")
        return RepositoryFile(content=content, sha=str(payload.get("sha", "")))

    def put_repository_file(self, path: str, content: str, *, branch: str, sha: str, message: str) -> bool:
        """在指定分支上创建或更新文件；sha 为空表示新建。

        token 缺少 Contents 写权限时 GitHub 返回 403，分支不存在时返回 404，这两种情况直接抛错让调用方记录原因。
        """

        if not self._is_configured():
            return False
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        self._request(
            "PUT",
            f"{self._contents_base_url}/{path}",
            json_payload=payload,
            allow_statuses={200, 201},
        )
        return True

    @property
    def _repository_base_url(self) -> str:
        return f"https://api.github.com/repos/{self.config.github_repo_owner}/{self.config.github_repo_name}"

    @property
    def _variables_base_url(self) -> str:
        return f"{self._repository_base_url}/actions/variables"

    @property
    def _contents_base_url(self) -> str:
        return f"{self._repository_base_url}/contents"

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
        json_payload: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        allow_statuses: set[int],
    ) -> requests.Response:
        def _call() -> requests.Response:
            assert self.session is not None
            response = self.session.request(
                method=method,
                url=url,
                json=json_payload,
                params=params,
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
            raise GitHubClientError(f"GitHub request failed: {url}: {exc}") from exc


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False
