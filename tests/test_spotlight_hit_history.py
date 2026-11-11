from __future__ import annotations

import json
import unittest
from datetime import date

from app.spotlight_hit_history import (
    count_previous_growth_days,
    merge_spotlight_hit_history,
    parse_spotlight_hit_history,
    serialize_spotlight_hit_history,
)


TODAY = date(2026, 11, 11)


class SpotlightHitHistoryTests(unittest.TestCase):
    def test_round_trip_keeps_groups_and_sorts_days_newest_first(self) -> None:
        history = merge_spotlight_hit_history({}, date(2026, 11, 10), [3, 1], [2])
        history = merge_spotlight_hit_history(history, TODAY, [], [2, 5])

        raw = serialize_spotlight_hit_history(history)

        self.assertEqual(
            {
                "version": 1,
                "days": {
                    "2026-11-11": {"new_face": [], "growth": [2, 5]},
                    "2026-11-10": {"new_face": [1, 3], "growth": [2]},
                },
            },
            json.loads(raw),
        )
        self.assertEqual(["2026-11-11", "2026-11-10"], list(json.loads(raw)["days"]))
        self.assertEqual(history, parse_spotlight_hit_history(raw))

    def test_same_day_keeps_first_write_and_old_days_are_trimmed(self) -> None:
        history = parse_spotlight_hit_history(
            '{"version":1,"days":{'
            '"2026-11-11":{"new_face":[1],"growth":[]},'
            '"2026-10-29":{"new_face":[],"growth":[9]},'
            '"2026-10-28":{"new_face":[],"growth":[9]}}}'
        )

        merged = merge_spotlight_hit_history(history, TODAY, [2], [3])

        # 当天重跑不覆盖第一次写入；保留 14 天（含当天），10-28 被裁掉。
        self.assertEqual(frozenset({1}), merged["2026-11-11"]["new_face"])
        self.assertEqual(["2026-10-29", "2026-11-11"], sorted(merged))

    def test_malformed_content_is_treated_as_empty_and_bad_items_are_skipped(self) -> None:
        self.assertEqual({}, parse_spotlight_hit_history(""))
        self.assertEqual({}, parse_spotlight_hit_history("not json"))
        self.assertEqual({}, parse_spotlight_hit_history('{"days":[]}'))

        history = parse_spotlight_hit_history(
            '{"days":{"bad-date":{"growth":[1]},"2026-11-10":{"growth":[1,"x","2"],"new_face":"oops"}}}'
        )

        self.assertEqual({"2026-11-10": {"new_face": frozenset(), "growth": frozenset({1, 2})}}, history)

    def test_growth_streak_stops_at_first_gap(self) -> None:
        history = merge_spotlight_hit_history({}, date(2026, 11, 7), [], [1])
        history = merge_spotlight_hit_history(history, date(2026, 11, 9), [], [1])
        history = merge_spotlight_hit_history(history, date(2026, 11, 10), [1], [1, 2])

        self.assertEqual(2, count_previous_growth_days(history, 1, TODAY))
        self.assertEqual(1, count_previous_growth_days(history, 2, TODAY))
        self.assertEqual(0, count_previous_growth_days(history, 3, TODAY))
        # 昨天没有记录时不往更早的日期找。
        self.assertEqual(0, count_previous_growth_days(history, 1, date(2026, 11, 12)))


if __name__ == "__main__":
    unittest.main()
