# project-performance-metrics Specification

## Purpose
TBD - created by archiving change add-project-performance-metrics. Update Purpose after archive.
## Requirements
### Requirement: Daily ARPDAU Column
系统 SHALL 在每个项目日报飞书表中包含 “ARPDAU” 列，并 SHALL 将该列放在 “付费率” 前方。系统 SHALL 使用 Roblox Creator Analytics 的 `AverageRevenuePerUser` 日粒度指标填充该列，不得从 ARPPU、付费率或总收入字段推算。

#### Scenario: ARPDAU column is inserted before payer conversion
- **WHEN** a project metrics sheet is rebuilt
- **THEN** the header SHALL contain “ARPDAU” immediately before “付费率”
- **THEN** later metric values SHALL remain under their semantic headers

#### Scenario: ARPDAU does not receive rank styling
- **WHEN** rank font reset, bold, or gradient colors are applied after the ARPDAU column is inserted
- **THEN** those styles SHALL apply only to rank columns
- **THEN** the “ARPDAU” value column SHALL NOT receive rank styling
- **THEN** columns that previously held rank values SHALL have stale rank font color and bold styling cleared when they now hold ordinary metric values

### Requirement: Daily Performance Columns
The system SHALL include project daily performance columns for client crash rate, tablet client memory usage, PC client memory usage, phone client memory usage, phone frame rate, server crashes, server memory usage, and server frame rate in each project metrics Feishu sheet. The system SHALL NOT include a generic client memory usage column.

#### Scenario: Sheet header includes performance columns
- **WHEN** a project metrics sheet is rebuilt
- **THEN** the header SHALL contain “推荐新增”, “广告新增”, “崩溃率”, “平板内存”, “PC内存”, “手机内存”, “移动端帧率”, “服务器崩溃数”, “服务器内存”, “服务器帧率”, and “更新时间” in that order after “Home Recommendation数量”
- **THEN** the header SHALL NOT contain “客户端内存”

### Requirement: Daily New Users By Acquisition Source
系统 SHALL 使用 Roblox Creator Analytics 的 `DailyActiveUsers` 日粒度指标，在筛选 `IsNewUser=New` 后按 `AcquisitionSource` 拆分每日新增用户。系统 SHALL 将 `Home Recommendation` 写入“推荐新增”，将 `Sponsored Ads` 写入“广告新增”，且 SHALL NOT 使用 `UniqueUsersWithImpressions` 填充这两列。

#### Scenario: Recommendation and sponsored new users share one breakdown query
- **WHEN** a report date needs either acquisition new-user field
- **THEN** the system SHALL query `DailyActiveUsers` with `IsNewUser=New` and an `AcquisitionSource` breakdown
- **THEN** values for `Home Recommendation` and `Sponsored Ads` SHALL be written to “推荐新增” and “广告新增” for the matching natural date

#### Scenario: Missing source is not converted to zero
- **WHEN** Roblox explicitly returns zero for an acquisition source and date
- **THEN** the corresponding sheet cell SHALL contain `0`
- **WHEN** Roblox omits the source or date from the response
- **THEN** the corresponding sheet cell SHALL remain blank

#### Scenario: Existing project sheets backfill acquisition new users
- **WHEN** an enabled project sheet contains historical dates with blank “推荐新增” or “广告新增” cells
- **THEN** those dates SHALL participate in the existing field-level backfill plan

### Requirement: Device Memory Actual Usage Semantics
The system SHALL populate “平板内存”, “PC内存”, and “手机内存” from `ClientMemoryUsageAvg` actual memory usage data for Tablet, Computer, and Phone respectively. The system SHALL NOT use `ClientMemoryUsagePercentageAvg` for these columns.

#### Scenario: Device breakdown actual values map to separate columns
- **WHEN** Roblox Analytics returns `ClientMemoryUsageAvg` values broken down by Tablet, Computer, and Phone for a report date
- **THEN** the system SHALL write the Tablet value to “平板内存”
- **THEN** the system SHALL write the Computer value to “PC内存”
- **THEN** the system SHALL write the Phone value to “手机内存”

#### Scenario: Device memory is converted from bytes to GB
- **WHEN** Roblox returns device memory values in bytes
- **THEN** the system SHALL average multiple values for the same platform and business date
- **THEN** the system SHALL divide the daily byte value by `1024^3` and format the result with a `GB` suffix and at most two decimal places

#### Scenario: Legacy percentages are scheduled for actual-value backfill
- **WHEN** an existing “平板内存”, “PC内存”, or “手机内存” cell contains a percentage
- **THEN** the percentage SHALL NOT be treated as a valid actual memory value
- **THEN** the corresponding actual-memory field SHALL participate in the field-level historical backfill plan
- **THEN** the cell SHALL remain blank when Roblox does not return an actual value

#### Scenario: Legacy byte-scaled values are scheduled for actual-value backfill
- **WHEN** an existing device-memory cell contains a value at or above `1024 GB`
- **THEN** the value SHALL be treated as an invalid legacy conversion result
- **THEN** the corresponding actual-memory field SHALL participate in the field-level historical backfill plan
- **THEN** the cell SHALL remain blank when Roblox does not return an actual value

### Requirement: Phone Frame Rate Semantics
The system SHALL populate “移动端帧率” from the `Phone` series of the daily `ClientFpsAvg` metric with a `Platform` breakdown. The query SHALL keep the existing Universe scope and SHALL NOT add a `Place` filter.

#### Scenario: Phone platform is selected from the frame-rate breakdown
- **WHEN** Roblox Analytics returns `ClientFpsAvg` series for multiple platforms
- **THEN** the system SHALL use only the series whose `Platform` breakdown value is `Phone`
- **THEN** the system SHALL average multiple Phone values for the same business date
- **THEN** Tablet and Computer values SHALL NOT contribute to “移动端帧率”

#### Scenario: Legacy all-platform frame rate is scheduled for Phone backfill
- **WHEN** an existing sheet uses the “客户端帧率” header
- **THEN** its all-platform values SHALL NOT be treated as valid Phone frame-rate values
- **THEN** the system SHALL rename the header to “移动端帧率” without shifting later columns
- **THEN** the corresponding `client_frame_rate` field SHALL participate in the historical backfill plan

### Requirement: Crash Rate Header Rename
The system SHALL treat the existing “报错率” value as client crash rate and display it as “崩溃率” after the migration.

#### Scenario: Existing error-rate header is migrated
- **WHEN** an existing sheet row contains a “报错率” column with a percentage value
- **THEN** the rebuilt row SHALL place that value under “崩溃率” and SHALL NOT create a separate duplicate crash-rate column

### Requirement: Row Date Metric Semantics
The system SHALL write performance metric values for the natural date shown in the row's “日期” cell, not for the date when the synchronization job runs.

#### Scenario: Historical row receives matching daily values
- **WHEN** Roblox Analytics returns a performance metric for a historical report date already present in the sheet
- **THEN** the system SHALL write that value into the row for the same report date

### Requirement: Historical Data Preservation
The system SHALL preserve existing non-empty sheet values when Roblox Analytics does not return a replacement value for a newly added or existing metric, except for legacy device-memory values that are incompatible with the current GB semantics and legacy all-platform client frame-rate values that are incompatible with the Phone-only semantics.

#### Scenario: Missing new metric leaves existing data intact
- **WHEN** a project metrics row already contains values and a new Roblox response omits one performance metric for that date
- **THEN** the system SHALL keep existing non-empty values in that row and leave the missing metric blank if no prior value exists

### Requirement: Sheet Layout And Styling Stability
The system MUST add the new columns without corrupting later column data or changing rank font color and bold behavior.

#### Scenario: Existing later columns retain formatting after acquisition columns are added
- **WHEN** an existing sheet does not yet contain “推荐新增” and “广告新增”
- **THEN** the system SHALL insert two physical columns immediately after “Home Recommendation数量”
- **THEN** all later columns SHALL move right with their existing values, fonts, and cell formatting
- **THEN** retrying a partially completed migration SHALL NOT insert the two columns again

#### Scenario: Rank styling remains scoped to rank columns
- **WHEN** the project metrics sheet is written after adding performance columns
- **THEN** rank font reset, bold, and color updates SHALL apply only to the configured rank columns and SHALL NOT apply to the new performance columns

### Requirement: Metric Formatting
The system SHALL format each performance metric according to its data type: crash rate as a percentage, device memory as GB, server crashes as a count, server memory as a readable MB value, and frame rate as a readable numeric frame-rate value.

#### Scenario: Returned metric values are formatted for the sheet
- **WHEN** Roblox Analytics returns daily performance metric values
- **THEN** the system SHALL convert them into stable display strings before writing them to Feishu
