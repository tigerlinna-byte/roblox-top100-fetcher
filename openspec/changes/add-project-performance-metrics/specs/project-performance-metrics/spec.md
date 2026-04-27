## ADDED Requirements

### Requirement: Daily Performance Columns
The system SHALL include project daily performance columns for client crash rate, tablet client memory percentage, PC client memory percentage, phone client memory percentage, client frame rate, server crashes, and server frame rate in each project metrics Feishu sheet. The system SHALL NOT include generic client memory usage or server memory usage columns.

#### Scenario: Sheet header includes performance columns
- **WHEN** a project metrics sheet is rebuilt
- **THEN** the header SHALL contain “崩溃率”, “平板内存”, “PC内存”, “手机内存”, “客户端帧率”, “服务器崩溃数”, “服务器帧率”, and “更新时间” in that order after “Home Recommendation数量”
- **THEN** the header SHALL NOT contain “客户端内存” or “服务器内存”

### Requirement: Device Memory Percentage Semantics
The system SHALL populate “平板内存”, “PC内存”, and “手机内存” from client memory usage percentage data for Tablet, Computer, and Phone respectively.

#### Scenario: Device breakdown values map to separate columns
- **WHEN** Roblox Analytics returns Client Memory Usage Percentage values broken down by Tablet, Computer, and Phone for a report date
- **THEN** the system SHALL write the Tablet value to “平板内存”
- **THEN** the system SHALL write the Computer value to “PC内存”
- **THEN** the system SHALL write the Phone value to “手机内存”

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
The system SHALL preserve existing non-empty sheet values when Roblox Analytics does not return a replacement value for a newly added or existing metric.

#### Scenario: Missing new metric leaves existing data intact
- **WHEN** a project metrics row already contains values and a new Roblox response omits one performance metric for that date
- **THEN** the system SHALL keep existing non-empty values in that row and leave the missing metric blank if no prior value exists

### Requirement: Sheet Layout And Styling Stability
The system MUST add the new columns without corrupting later column data or changing rank font color and bold behavior.

#### Scenario: Rank styling remains scoped to rank columns
- **WHEN** the project metrics sheet is written after adding performance columns
- **THEN** rank font reset, bold, and color updates SHALL apply only to the configured rank columns and SHALL NOT apply to the new performance columns

### Requirement: Metric Formatting
The system SHALL format each performance metric according to its data type: crash rate and device memory as percentages, server crashes as a count, and frame rate as a readable numeric frame-rate value.

#### Scenario: Returned metric values are formatted for the sheet
- **WHEN** Roblox Analytics returns daily performance metric values
- **THEN** the system SHALL convert them into stable display strings before writing them to Feishu
