from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from .config import Config
from .models import GameRecord, now_iso
from .retry import with_retry


GET_SORTS_URL = "https://apis.roblox.com/explore-api/v1/get-sorts"
GET_SORT_CONTENT_URL = "https://apis.roblox.com/explore-api/v1/get-sort-content"
GAMES_DETAIL_URL = "https://games.roblox.com/v1/games"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/games/icons"
GAME_LOCALIZATION_URL_TEMPLATE = "https://gameinternationalization.roblox.com/v1/name-description/games/{universe_id}"
TOP_TRENDING_SORT_ID_CANDIDATES = (
    "top-trending",
    "trending",
    "top-charts",
    "charts",
)
PREFERRED_LOCALIZATION_CODES = (
    "zh-cn",
    "zh_hans_cn",
    "zh-hans-cn",
    "zh-hans",
    "zh_cn",
)
ROBLOX_DISCOVER_REFERER = "https://www.roblox.com/discover"
ROBLOX_DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.roblox.com",
    "Referer": ROBLOX_DISCOVER_REFERER,
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
}


class RobloxClientError(RuntimeError):
    pass


@dataclass
class RobloxClient:
    config: Config
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()

    def fetch_top_games(self) -> list[GameRecord]:
        return self._fetch_games_for_sort(self._resolve_top_games_sort_id())

    def fetch_top_trending_games(self) -> list[GameRecord]:
        configured_sort_id = self._resolve_top_trending_sort_id()
        return self.fetch_games_by_sort_id(configured_sort_id)

    def fetch_games_by_sort_id(self, sort_id: str) -> list[GameRecord]:
        candidate_sort_ids = [sort_id]
        candidate_sort_ids.extend(
            sort_id
            for sort_id in TOP_TRENDING_SORT_ID_CANDIDATES
            if sort_id != candidate_sort_ids[0]
        )

        last_error: Exception | None = None
        for candidate_sort_id in candidate_sort_ids:
            try:
                return self._fetch_games_for_sort(candidate_sort_id)
            except RobloxClientError as exc:
                last_error = exc
                continue

        raise RobloxClientError(f"Unable to fetch games for sort {sort_id}.") from last_error

    def _fetch_games_for_sort(self, sort_id: str) -> list[GameRecord]:
        payload = self._fetch_sort_content(sort_id)
        games = self._extract_games(payload)
        if not games:
            raise RobloxClientError("No game entries found in Roblox response.")

        games = games[: self.config.api_limit]
        universe_ids = [str(_as_int(_pick(item, "universeId", "universe_id"))) for item in games]
        details_map = self._fetch_game_details(universe_ids)
        localized_names = self._fetch_localized_names(universe_ids)
        thumbnail_urls = self._fetch_thumbnail_urls(universe_ids)

        fetched_at = now_iso()
        records: list[GameRecord] = []
        for index, raw in enumerate(games, start=1):
            universe_id = _as_int(_pick(raw, "universeId", "universe_id"))
            details = details_map.get(universe_id, {})
            creator_obj = details.get("creator") if isinstance(details, dict) else {}
            creator_name = ""
            if isinstance(creator_obj, dict):
                creator_name = str(creator_obj.get("name", ""))

            records.append(
                GameRecord(
                    rank=index,
                    universe_id=universe_id or None,
                    place_id=_as_int(
                        _pick(raw, "placeId", "rootPlaceId", "place_id", "id", default=0)
                    ),
                    name=str(_pick(raw, "name", "title", default=_pick(details, "name", default=""))),
                    localized_name=localized_names.get(universe_id, ""),
                    genre=_resolve_game_genre(raw, details),
                    thumbnail_url=thumbnail_urls.get(universe_id, ""),
                    creator=creator_name,
                    playing=_as_int(
                        _pick(
                            raw,
                            "playing",
                            "playerCount",
                            "concurrentPlayers",
                            default=_pick(details, "playing", default=0),
                        )
                    ),
                    visits=_as_int(
                        _pick(raw, "visits", "visitCount", default=_pick(details, "visits", default=0))
                    ),
                    up_votes=_as_int(
                        _pick(
                            raw,
                            "totalUpVotes",
                            "upVotes",
                            "up_votes",
                            "upVoteCount",
                            default=_pick(details, "upVotes", default=0),
                        )
                    ),
                    down_votes=_as_int(
                        _pick(
                            raw,
                            "totalDownVotes",
                            "downVotes",
                            "down_votes",
                            "downVoteCount",
                            default=_pick(details, "downVotes", default=0),
                        )
                    ),
                    fetched_at=fetched_at,
                    created_at=str(
                        _pick(
                            details,
                            "created",
                            "createdAt",
                            default=_pick(raw, "created", "createdAt", default=""),
                        )
                    ),
                    updated_at=str(
                        _pick(
                            details,
                            "updated",
                            "updatedAt",
                            default=_pick(raw, "updated", "updatedAt", default=""),
                        )
                    ),
                )
            )
        return records

    def _resolve_top_games_sort_id(self) -> str:
        if self.config.roblox_sort_id:
            return self.config.roblox_sort_id

        for item in self._fetch_sorts():
            sort_id = str(_pick(item, "id", "sortId", default=""))
            if sort_id == "top-playing-now":
                return sort_id
        raise RobloxClientError("Unable to discover sort id.")

    def _resolve_top_trending_sort_id(self) -> str:
        if self.config.roblox_top_trending_sort_id:
            return self.config.roblox_top_trending_sort_id

        for item in self._fetch_sorts():
            sort_id = str(_pick(item, "id", "sortId", default=""))
            sort_name = str(_pick(item, "name", "title", "displayName", default=""))
            normalized_name = " ".join(sort_name.lower().split())
            if sort_id in TOP_TRENDING_SORT_ID_CANDIDATES or normalized_name in {
                "top trending",
                "trending",
                "top charts",
                "charts",
            }:
                return sort_id
        return TOP_TRENDING_SORT_ID_CANDIDATES[0]

    def _fetch_sorts(self) -> list[dict[str, Any]]:
        response = self._request_json(
            "GET",
            GET_SORTS_URL,
            params={"sessionId": str(uuid.uuid4())},
        )
        items = _extract_sort_items(response)
        self._log_discovered_sorts(items)
        return items

    @staticmethod
    def _log_discovered_sorts(items: list[dict[str, Any]]) -> None:
        if not items:
            logging.info("Roblox explore sorts: none returned")
            return

        summary = [
            {
                "id": str(_pick(item, "id", "sortId", default="")),
                "name": str(_pick(item, "name", "title", "displayName", default="")),
            }
            for item in items
        ]
        logging.info("Roblox explore sorts discovered: %s", summary)

    def _fetch_sort_content(self, sort_id: str) -> dict[str, Any]:
        params = {
            "sessionId": str(uuid.uuid4()),
            "sortId": sort_id,
            "device": "all",
            "country": "all",
        }
        return self._request_json("GET", GET_SORT_CONTENT_URL, params=params)

    def _fetch_game_details(self, universe_ids: list[str]) -> dict[int, dict[str, Any]]:
        universe_ids = [uid for uid in universe_ids if uid and uid != "0"]
        if not universe_ids:
            return {}

        details_map: dict[int, dict[str, Any]] = {}
        for chunk in _chunked(universe_ids, size=40):
            response = self._request_json(
                "GET",
                GAMES_DETAIL_URL,
                params={"universeIds": ",".join(chunk)},
            )
            for item in _extract_list(response, "data"):
                uid = _as_int(_pick(item, "id", default=0))
                if uid:
                    details_map[uid] = item
        return details_map

    def _fetch_localized_names(self, universe_ids: list[str]) -> dict[int, str]:
        result: dict[int, str] = {}
        for raw_universe_id in universe_ids:
            universe_id = _as_int(raw_universe_id)
            if not universe_id or universe_id in result:
                continue
            try:
                payload = self._request_json(
                    "GET",
                    GAME_LOCALIZATION_URL_TEMPLATE.format(universe_id=universe_id),
                )
            except RobloxClientError:
                logging.warning("Failed to fetch localized game name for universe %s.", universe_id)
                continue

            localized_name = _extract_preferred_localized_name(payload)
            if localized_name:
                result[universe_id] = localized_name
        return result

    def _fetch_thumbnail_urls(self, universe_ids: list[str]) -> dict[int, str]:
        filtered_ids = [uid for uid in universe_ids if uid and uid != "0"]
        if not filtered_ids:
            return {}

        result: dict[int, str] = {}
        for chunk in _chunked(filtered_ids, size=100):
            try:
                response = self._request_json(
                    "GET",
                    THUMBNAILS_URL,
                    params={
                        "universeIds": ",".join(chunk),
                        "size": "150x150",
                        "format": "Png",
                        "isCircular": "false",
                        "returnPolicy": "PlaceHolder",
                    },
                )
            except RobloxClientError:
                logging.warning("Failed to fetch thumbnail urls for universes %s.", ",".join(chunk))
                continue

            for item in _extract_list(response, "data"):
                target_id = _as_int(_pick(item, "targetId", "target_id", default=0))
                image_url = str(_pick(item, "imageUrl", "image_url", default="")).strip()
                if target_id and image_url:
                    result[target_id] = image_url
        return result

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            assert self.session is not None
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_payload,
                headers=self._build_request_headers(),
                timeout=self.config.request_timeout_seconds,
            )
            if response.status_code >= 400:
                raise requests.HTTPError(
                    f"HTTP {response.status_code}: {response.text[:300]}", response=response
                )
            return response.json()

        try:
            return with_retry(
                _call,
                attempts=self.config.retry_max_attempts,
                base_backoff_seconds=self.config.retry_backoff_seconds,
                is_retryable=_is_retryable_exception,
            )
        except Exception as exc:  # noqa: BLE001
            raise RobloxClientError(f"Request failed: {url}") from exc

    def _build_request_headers(self) -> dict[str, str]:
        """为榜单接口构造带登录态的浏览器请求头。"""

        headers = dict(ROBLOX_DEFAULT_HEADERS)
        cookie_header = _normalize_roblox_security_cookie(self.config.roblox_creator_cookie)
        if cookie_header:
            headers["Cookie"] = cookie_header
        return headers

    @staticmethod
    def _extract_games(payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            _extract_list(payload, "games"),
            _extract_list(payload, "data"),
            _extract_list(payload, "items"),
        ]
        for first in list(candidates):
            if not first:
                continue
            if first and isinstance(first[0], dict):
                nested = [
                    _extract_list(first[0], "games"),
                    _extract_list(first[0], "items"),
                    _extract_list(first[0], "content"),
                    _extract_list(first[0], "gameTiles"),
                ]
                candidates.extend(nested)

        for items in candidates:
            if items and isinstance(items[0], dict):
                return items
        return []


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        if response is None:
            return False
        return response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
    return False


def _pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_list(data: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    current: Any = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return []
    if isinstance(current, list):
        return [item for item in current if isinstance(item, dict)]
    return []


def _chunked(items: list[str], *, size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _resolve_game_genre(raw: dict[str, Any], details: dict[str, Any]) -> str:
    """优先返回更具体的游戏类型，避免把泛化的 All 写进表格。"""

    candidates = [
        _pick(details, "genre_l2", default=""),
        _pick(raw, "genre_l2", default=""),
        _pick(details, "genre", default=""),
        _pick(raw, "genre", default=""),
        _pick(details, "genre_l1", default=""),
        _pick(raw, "genre_l1", default=""),
    ]
    fallback = ""
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        if not fallback:
            fallback = text
        if text.casefold() != "all":
            return text
    return fallback


def _extract_sort_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        _extract_list(payload, "sorts"),
        _extract_list(payload, "data"),
        _extract_list(payload, "items"),
        _extract_list(payload, "sorts", "data"),
        _extract_list(payload, "sorts", "items"),
        _extract_list(payload, "data", "items"),
    ]
    for items in candidates:
        if items:
            return items
    return []


def _extract_preferred_localized_name(payload: dict[str, Any]) -> str:
    candidates = _collect_localization_entries(payload)
    for code in PREFERRED_LOCALIZATION_CODES:
        for item in candidates:
            language_code = str(
                _pick(
                    item,
                    "languageCode",
                    "language_code",
                    "localeCode",
                    "locale_code",
                    "language",
                    default="",
                )
            ).strip().lower()
            if language_code == code:
                localized_name = str(_pick(item, "name", "displayName", "title", default="")).strip()
                if localized_name:
                    return localized_name
    return ""


def _collect_localization_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        _extract_list(payload, "data"),
        _extract_list(payload, "nameDescriptionLocalizationTargets"),
        _extract_list(payload, "localizedGameNames"),
        _extract_list(payload, "gameNameLocalizationTargets"),
    ]
    for items in candidates:
        if items:
            return items
    if any(key in payload for key in ("languageCode", "localeCode", "name", "displayName", "title")):
        return [payload]
    return []


def _normalize_roblox_security_cookie(raw_cookie: str) -> str:
    value = raw_cookie.strip()
    if not value:
        return ""
    if value.startswith(".ROBLOSECURITY="):
        return value
    return f".ROBLOSECURITY={value}"
