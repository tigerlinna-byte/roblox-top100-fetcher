## Context

Project daily metrics are synchronized from Roblox Creator Analytics into one Feishu spreadsheet per configured project. The existing sheet already includes `client_crash_rate`, sourced from `ClientCrashRate15m`, but the visible header is “报错率”. This is a naming mismatch: the source metric is a crash-rate metric, not a general error-rate metric.

The current table builder normalizes rows by header semantics and preserves non-empty historical values when a new fetch does not provide replacement data. Rank styling is limited to the existing rank columns. The change should extend that model instead of introducing positional rewrites that could shift existing data.

## Goals / Non-Goals

**Goals:**

- Rename the existing “报错率” column to “崩溃率” without creating a duplicate client crash rate metric.
- Add daily client frame rate, server crash count, and server frame rate columns between “崩溃率” and “更新时间”.
- Treat each value as the metric for the date shown in the row's “日期” column.
- Preserve existing sheet data, especially columns after the insertion point and rank font styling.
- Backfill newly available values for dates in the normal project metrics query window.

**Non-Goals:**

- Expanding project metrics beyond the current configured projects.
- Changing the Top Trending or Top 100 report modes.
- Changing benchmark/rank color semantics.
- Writing partial or inferred values when Roblox Analytics does not return a metric for a date.

## Decisions

### Reuse `client_crash_rate` for “崩溃率”

`client_crash_rate` already maps to Roblox `ClientCrashRate15m`; the visible Chinese header should be corrected from “报错率” to “崩溃率”. This avoids a duplicate column and keeps existing historical values meaningful.

Alternative considered: add a new “崩溃率” column and leave “报错率” in place. That would create two columns with the same underlying meaning and make historical interpretation worse.

### Add fields before `fetched_at`

The new metric fields should be appended after `client_crash_rate` and before `fetched_at` in the domain model, row builder, header mapping, and Feishu sheet layout. `fetched_at` remains the final column because it describes synchronization time, not Roblox metric time.

Alternative considered: append new fields after `更新时间`. That would avoid moving the timestamp column, but it would make the sheet less coherent and conflict with the requested placement after crash rate.

### Use daily average aggregation for frame-rate metrics

Client frame rate and server frame rate should use daily values for the row date. If Roblox returns multiple data points within a day for these metrics, the implementation should average them for that business date. If Roblox returns a daily-granularity value, that value can be used directly.

Server crashes is a count metric, so it should use the daily count/value returned by Roblox rather than an average unless Roblox only exposes finer-grained count buckets that must be summed for the day.

### Keep migration semantic, not positional

Existing rows should be read by header names where possible. Legacy headers containing “报错率” should still populate `client_crash_rate`, now displayed as “崩溃率”. Newly introduced columns should default to blank when older sheets have no matching data.

This keeps future migrations less brittle and directly addresses the requirement that newly inserted columns do not damage later data.

### Verify Roblox metric keys before finalizing implementation

The Creator Dashboard frontend metric enums identify the retained daily average/count metrics as `ClientFpsAvg`, `ServerCrashCount`, and `ServerFrameRateAvg`. These should be used for the direct analytics requests instead of the shorter URL-level display metric names.

## Risks / Trade-offs

- Roblox metric names may differ from URL display names -> use the Creator Dashboard frontend enum names and verify with real Creator Analytics requests.
- Daily granularity may not be available for every new metric -> support aggregation from finer-grained data when the API requires it.
- Feishu read range currently ends at column Q -> update it to cover the new final column or historical timestamp values may not be read back.
- Column insertion could shift styles -> keep rank style ranges derived from rank fields and update only column widths/read-write dimensions.
- Newly unavailable historical metrics may remain blank -> preserve blanks rather than fabricating data.

## Migration Plan

1. Update model and sheet header mapping so old “报错率” values migrate into the renamed “崩溃率” column.
2. Extend Roblox metric fetch configuration and metadata requests for the new fields.
3. Expand Feishu read/write ranges and column widths to the new final column.
4. Keep rank font reset/bold/color ranges bound to rank fields only.
5. Run unit tests for row order, legacy migration, field formatting, metric extraction, and styling ranges.
6. Deploy normally through the existing GitHub Actions workflow. Rollback is code-only; existing Feishu data remains readable because values are stored in plain cells.

## Open Questions

- Confirm units returned by frame-rate metrics so formatting can be stable and readable.
