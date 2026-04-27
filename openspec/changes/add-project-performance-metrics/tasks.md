## 1. Metric Discovery

- [x] 1.1 Confirm Roblox Analytics internal metric keys for client frame rate, server crashes, and server frame rate using Creator Analytics network traffic or authenticated metadata.
- [ ] 1.2 Confirm authenticated Roblox query payload shape for `ClientMemoryUsagePercentageAvg` with platform/device breakdown.
- [x] 1.3 Confirm units and aggregation behavior for device memory percentage, frame-rate, and server crash metrics.

## 2. Data Model And Fetching

- [x] 2.1 Add project daily metric fields for tablet memory percentage, PC memory percentage, phone memory percentage, client frame rate, server crashes, and server frame rate.
- [x] 2.2 Extend direct Roblox metric query specs and metadata requests for the new fields.
- [x] 2.3 Format device memory and crash rate as percentages, continuous performance metrics as daily averages, and server crashes as daily count values.
- [x] 2.4 Populate the new fields when building `ProjectDailyMetricsRecord` instances.

## 3. Feishu Sheet Mapping

- [x] 3.1 Rename the visible crash-rate header from “报错率” to “崩溃率” while preserving old “报错率” input during row normalization.
- [x] 3.2 Insert “平板内存”, “PC内存”, “手机内存”, and the retained performance columns after “崩溃率” and before “更新时间”.
- [x] 3.3 Expand the project metrics Feishu read/write range and column width configuration through the new final column.
- [x] 3.4 Keep rank font reset, bold, and color updates scoped to the existing rank columns only.

## 4. Migration And Preservation

- [x] 4.1 Verify old header rows with “报错率” migrate to the new “崩溃率” column.
- [x] 4.2 Verify existing rows preserve non-empty data when newly fetched metric values are missing.
- [x] 4.3 Verify the shifted “更新时间” value remains attached to the timestamp field after new columns are inserted.

## 5. Tests And Validation

- [x] 5.1 Update sheet tests for the new header order, row value order, legacy migration, and styling ranges.
- [x] 5.2 Update Roblox creator metrics client tests for new metric extraction and formatting.
- [x] 5.3 Run the Python unit test suite and inspect failures related to project metrics.
- [ ] 5.4 If authenticated Roblox credentials are available, run a project metrics fetch dry run and confirm newly populated dates match the row dates.
