from __future__ import annotations

import unittest

from app.retry import RetryError, with_retry


class RetryTests(unittest.TestCase):
    def test_retries_until_success(self) -> None:
        counter = {"n": 0}

        def flaky() -> int:
            counter["n"] += 1
            if counter["n"] < 3:
                raise ValueError("try again")
            return 7

        result = with_retry(
            flaky,
            attempts=3,
            base_backoff_seconds=0.0,
            is_retryable=lambda exc: isinstance(exc, ValueError),
        )
        self.assertEqual(7, result)
        self.assertEqual(3, counter["n"])

    def test_raises_retry_error_after_attempts(self) -> None:
        def always_fail() -> int:
            raise RuntimeError("nope")

        with self.assertRaises(RetryError):
            with_retry(
                always_fail,
                attempts=2,
                base_backoff_seconds=0.0,
                is_retryable=lambda _exc: True,
            )


if __name__ == "__main__":
    unittest.main()
