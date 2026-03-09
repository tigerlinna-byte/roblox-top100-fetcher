from __future__ import annotations

import json
from datetime import date, datetime
from dataclasses import dataclass
from typing import Callable

import requests

from .config import Config
from .retry import with_retry


class FeishuClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpreadsheetInfo:
    spreadsheet_token: str
    sheet_ids: tuple[str, ...]
    url: str


@dataclass(frozen=True)
class SheetInfo:
    sheet_id: str
    title: str


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
            json_transform=_stringify_feishu_content,
        )

    def create_spreadsheet(self, title: str) -> SpreadsheetInfo:
        access_token = self._fetch_tenant_access_token()
        data = self._request_json(
            "POST",
            "https://open.feishu.cn/open-apis/sheets/v3/spreadsheets",
            json_payload={"title": title},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        spreadsheet = data.get("data", {}).get("spreadsheet", {})
        spreadsheet_token = str(
            spreadsheet.get("spreadsheet_token")
            or spreadsheet.get("spreadsheetToken")
            or data.get("data", {}).get("spreadsheet_token")
            or ""
        )
        if not spreadsheet_token:
            raise FeishuClientError("Feishu spreadsheet response missing spreadsheet token")

        sheet_ids = _extract_sheet_ids(spreadsheet)
        if not sheet_ids:
            sheet_ids = _extract_sheet_ids(data.get("data", {}))
        url = str(spreadsheet.get("url") or _build_spreadsheet_url(spreadsheet_token))
        return SpreadsheetInfo(
            spreadsheet_token=spreadsheet_token,
            sheet_ids=sheet_ids,
            url=url,
        )

    def ensure_sheet_set(
        self,
        spreadsheet_token: str,
        existing_sheet_id: str | None,
        sheet_titles: list[str],
    ) -> tuple[str, ...]:
        if not existing_sheet_id:
            existing_sheets = self.query_sheets(spreadsheet_token)
            if existing_sheets:
                existing_sheet_id = existing_sheets[0].sheet_id

        access_token = self._fetch_tenant_access_token()
        requests_payload: list[dict] = []
        start_index = 0
        created_ids: list[str] = []

        if existing_sheet_id:
            requests_payload.append(
                {
                    "updateSheet": {
                        "properties": {
                            "sheetId": existing_sheet_id,
                            "title": sheet_titles[0],
                            "index": 0,
                        },
                        "fields": "title,index",
                    }
                }
            )
            created_ids.append(existing_sheet_id)
            start_index = 1

        for index, title in enumerate(sheet_titles[start_index:], start=start_index):
            requests_payload.append(
                {
                    "addSheet": {
                        "properties": {
                            "title": title,
                            "index": index,
                        }
                    }
                }
            )

        data = self._request_json(
            "POST",
            f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
            json_payload={"requests": requests_payload},
            headers={"Authorization": f"Bearer {access_token}"},
        )

        for reply in data.get("data", {}).get("replies", []):
            add_sheet = reply.get("addSheet", {}) if isinstance(reply, dict) else {}
            sheet_id = _extract_sheet_id(add_sheet)
            if sheet_id:
                created_ids.append(sheet_id)

        if len(created_ids) != len(sheet_titles):
            existing_by_title = {
                sheet.title: sheet.sheet_id for sheet in self.query_sheets(spreadsheet_token)
            }
            created_ids = [existing_by_title[title] for title in sheet_titles if title in existing_by_title]
        if len(created_ids) != len(sheet_titles):
            raise FeishuClientError("Feishu sheet setup response missing created sheet ids")

        self.delete_extra_sheets(
            spreadsheet_token,
            keep_sheet_ids=set(created_ids),
        )
        return tuple(created_ids)

    def write_sheet_values(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        values: list[list[object]],
    ) -> None:
        access_token = self._fetch_tenant_access_token()
        column_letter = _column_letter(max((len(row) for row in values), default=1))
        range_ref = f"{sheet_id}!A1:{column_letter}{len(values)}"
        self._request_json(
            "PUT",
            f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values",
            json_payload={
                "valueRange": {
                    "range": range_ref,
                    "values": _serialize_sheet_values(values),
                }
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def query_sheets(self, spreadsheet_token: str) -> tuple[SheetInfo, ...]:
        access_token = self._fetch_tenant_access_token()
        data = self._request_json(
            "GET",
            f"https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        sheets = _extract_sheet_infos(data.get("data", {}))
        return tuple(sheets)

    def delete_extra_sheets(self, spreadsheet_token: str, *, keep_sheet_ids: set[str]) -> None:
        existing_sheets = self.query_sheets(spreadsheet_token)
        redundant = [sheet.sheet_id for sheet in existing_sheets if sheet.sheet_id not in keep_sheet_ids]
        if not redundant:
            return

        access_token = self._fetch_tenant_access_token()
        requests_payload = [{"deleteSheet": {"sheetId": sheet_id}} for sheet_id in redundant]
        self._request_json(
            "POST",
            f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/sheets_batch_update",
            json_payload={"requests": requests_payload},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    def update_spreadsheet_title(self, spreadsheet_token: str, title: str) -> None:
        del spreadsheet_token, title

    def apply_sheet_layout(
        self,
        spreadsheet_token: str,
        sheet_id: str,
        *,
        rank_width: int,
        game_name_width: int,
        developer_width: int,
    ) -> None:
        access_token = self._fetch_tenant_access_token()
        for start_index, end_index, width in (
            (0, 1, rank_width),
            (1, 2, game_name_width),
            (5, 6, developer_width),
        ):
            self._request_json(
                "PUT",
                f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/dimension_range",
                json_payload={
                    "dimension": {
                        "sheetId": sheet_id,
                        "majorDimension": "COLUMNS",
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "dimensionProperties": {
                        "fixedSize": width,
                    },
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
        json_transform: Callable[[dict | None], dict | None] | None = None,
        requires_feishu_code: bool = True,
    ) -> dict:
        def _call() -> dict:
            assert self.session is not None
            payload = json_transform(json_payload) if json_transform else json_payload
            response = self.session.request(
                method=method,
                url=url,
                json=payload,
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


def _stringify_feishu_content(payload: dict | None) -> dict | None:
    if not payload or "content" not in payload:
        return payload

    transformed = dict(payload)
    transformed["content"] = json.dumps(
        payload["content"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return transformed


def _extract_sheet_id(payload: dict) -> str:
    sheet_ids = _extract_sheet_ids(payload)
    if sheet_ids:
        return sheet_ids[0]
    return ""


def _extract_sheet_ids(payload: dict) -> tuple[str, ...]:
    sheets = payload.get("sheets")
    result: list[str] = []
    if isinstance(sheets, list) and sheets:
        first = sheets[0]
        for item in sheets:
            value = _extract_single_sheet_id(item)
            if value:
                result.append(value)
        if result:
            return tuple(result)

    value = _extract_single_sheet_id(payload)
    if value:
        return (value,)
    return ()


def _extract_sheet_infos(payload: dict) -> list[SheetInfo]:
    sheets = payload.get("sheets")
    if not isinstance(sheets, list):
        return []

    result: list[SheetInfo] = []
    for item in sheets:
        if not isinstance(item, dict):
            continue
        sheet_id = _extract_single_sheet_id(item)
        properties = item.get("properties")
        title = ""
        if isinstance(properties, dict):
            title = str(properties.get("title", ""))
        if not title:
            title = str(item.get("title", ""))
        if sheet_id:
            result.append(SheetInfo(sheet_id=sheet_id, title=title))
    return result


def _extract_single_sheet_id(payload: dict) -> str:
    properties = payload.get("properties")
    if isinstance(properties, dict):
        value = properties.get("sheet_id") or properties.get("sheetId")
        if value:
            return str(value)

    value = payload.get("sheet_id") or payload.get("sheetId")
    if value:
        return str(value)
    return ""


def _build_spreadsheet_url(spreadsheet_token: str) -> str:
    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def _column_letter(index: int) -> str:
    value = max(1, index)
    letters: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _serialize_sheet_values(values: list[list[object]]) -> list[list[object]]:
    return [[_serialize_sheet_cell(cell) for cell in row] for row in values]


def _serialize_sheet_cell(cell: object) -> object:
    if isinstance(cell, datetime):
        return cell.date().isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    return cell
