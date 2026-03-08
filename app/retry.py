from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


class RetryError(RuntimeError):
    pass


def with_retry(
    func: Callable[[], T],
    *,
    attempts: int,
    base_backoff_seconds: float,
    is_retryable: Callable[[Exception], bool],
) -> T:
    last_error: Exception | None = None
    for idx in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if idx >= attempts or not is_retryable(exc):
                break
            time.sleep(base_backoff_seconds * (2 ** (idx - 1)))
    raise RetryError(f"Failed after {attempts} attempts") from last_error
