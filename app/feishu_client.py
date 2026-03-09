from __future__ import annotations

from dataclasses import dataclass

import requests

from .config import Config
from .retry import with_retry


class FeishuClientError(RuntimeError):
    pass


@dataclass
class FeishuClient:
    config: Config
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def send_group_markdown(self, markdown_text: str) -> None:
        if self.config.run_chat_id and self._has_app_credentials():
            self._send_group_text_via_app(markdown_text)
            return

        if not self.config.feishu_bot_webhook:
            return

        self._request_json(
            "POST",
            self.config.feishu_bot_webhook,
            json_payload={
                "msg_type": "text",
                "content": {"text": markdown_text},
            },
            requires_feishu_code=False,
        )

    def _has_app_credentials(self) -> bool:
        return bool(self.config.feishu_app_id and self.config.feishu_app_secret)

    def _send_group_text_via_app(self, markdown_text: str) -> None:
        access_token = self._fetch_tenant_access_token()
        self._request_json(
            "POST",
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            json_payload={
                "receive_id": self.config.run_chat_id,
                "msg_type": "text",
                "content": {"text": markdown_text},
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def _fetch_tenant_access_token(self) -> str:
        data = self._request_json(
            "POST",
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json_payload={
                "app_id": self.config.feishu_app_id,
                "app_secret": self.config.feishu_app_secret,
            },
        )
        token = data.get("tenant_access_token", "")
        if not token:
            raise FeishuClientError("Feishu auth response missing tenant_access_token")
        return token

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        json_payload: dict | None = None,
        headers: dict[str, str] | None = None,
        requires_feishu_code: bool = True,
    ) -> dict:
        def _call() -> dict:
            assert self.session is not None
            response = self.session.request(
                method=method,
                url=url,
                json=json_payload,
                headers=headers,
                timeout=self.config.request_timeout_seconds,
            )
            if response.status_code >= 400:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}: {response.text[:400]}",
                    response=response,
                )
            data = response.json()
            if requires_feishu_code and data.get("code", 0) != 0:
                raise FeishuClientError(f"Feishu API error: {data}")
            return data

        try:
            return with_retry(
                _call,
                attempts=self.config.retry_max_attempts,
                base_backoff_seconds=self.config.retry_backoff_seconds,
                is_retryable=_is_retryable_exception,
            )
        except Exception as exc:  # noqa: BLE001
            raise FeishuClientError(f"Feishu request failed: {url}") from exc


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False
