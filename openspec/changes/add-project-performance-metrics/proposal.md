## Why

项目日报当前只写入一个名为“报错率”的稳定性字段，但实际数据来源是 Roblox Creator Analytics 的 Client crash rate，中文表头不够准确，也缺少内存、帧率和服务器稳定性指标。运营需要在同一张按日期排列的日报表中查看每个日期对应的客户端与服务器性能数据，并能补齐历史日期。

## What Changes

- 将现有“报错率”表头改为“崩溃率”，继续使用当前 `client_crash_rate` / `ClientCrashRate15m` 数据源，不新增重复的客户端崩溃率列。
- 在“崩溃率”后、“更新时间”前新增以下项目日报列：
  - 客户端内存，对应 Client memory usage。
  - 客户端帧率，对应 Client frame rate。
  - 服务器崩溃数，对应 Server crashes。
  - 服务器内存，对应 Server memory usage。
  - 服务器帧率，对应 Server frame rate。
- 新增列按左侧日期行对应的自然日写入数据，不表示程序运行当天。
- 对已有日报表执行语义化迁移，确保新增列不会挤错或覆盖后续列的历史数据。
- 保持既有排名列字体颜色和加粗规则不受新增列影响。
- 补齐最近窗口内历史日期可获得的新指标数据；对于 Roblox 尚未返回的数据保持空白，不清除已有有效历史值。

## Capabilities

### New Capabilities

- `project-performance-metrics`: Defines daily project performance and stability metrics synchronized from Roblox Creator Analytics into Feishu project metric sheets.

### Modified Capabilities

- None.

## Impact

- Affected code:
  - `app/project_metrics_models.py`
  - `app/roblox_creator_metrics_client.py`
  - `app/project_metrics_sheet.py`
  - `app/main.py`
  - related unit tests under `tests/`
- Affected external systems:
  - Roblox Creator Analytics Query Gateway metric queries.
  - Feishu spreadsheet read/write ranges and column widths.
- No breaking change is expected for existing sheet rows because migration should map values by header semantics and preserve existing non-empty values.
