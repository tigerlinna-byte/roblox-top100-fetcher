# 项目维护上下文手册

这份文档用于帮助维护者在更换电脑、切换账号、长时间中断后，快速恢复项目上下文。

本文档以当前仓库代码为准，优先级高于旧 README、历史口头约定和外部截图。凡是涉及触发方式、配置变量、表格结构、定时策略、消息样式、数据口径的变动，都必须同步更新本文件。

## 1. 项目当前到底在做什么

这个仓库当前维护的是一套“Roblox 数据 -> GitHub Actions -> 飞书”的自动化链路，而不是一个单独的脚本。

当前有 4 条真实运行链路：

| 运行模式 | 入口 | 数据来源 | 结果 |
| --- | --- | --- | --- |
| `top100_message` | 本地运行、GitHub Actions 手动触发、飞书 `/roblox-top100` | Roblox 榜单接口 | 输出 JSON/CSV，并发送 Top100 文本摘要 |
| `top_trending_sheet` | 飞书 `/roblox-top-day`、Cloudflare Cron `0 1 * * *` | Roblox 榜单接口 | 发送 `今日关注` 卡片，更新历史排名，并输出 JSON |
| `roblox_project_daily_metrics` | 飞书 `/roblox-project-metrics`、Cloudflare Cron `10 1 * * *` | Roblox Creator Analytics 接口 | 更新每个项目自己的飞书表，并发送表格链接 |
| `roblox_money` | test 群 `/roblox-money`、Cloudflare Cron `20 1 * * *` | Roblox Creator Analytics 收入指标 | 发送第一项目和 `Troll ur friends` 的收入卡片日报，并输出 JSON/CSV |

如果有人还把它理解成“抓一下 Top100 然后发群”，那已经是过时认知。

## 2. 端到端架构

当前系统分 5 层：

1. Cloudflare Worker
   - 文件：[`worker/src/index.js`](../worker/src/index.js)
   - 负责接收飞书事件回调
   - 负责接收 Cloudflare Cron Trigger
   - 负责事件去重
   - 负责调用 GitHub Actions `workflow_dispatch`

2. GitHub Actions
   - 文件：[`/.github/workflows/roblox_rank_sync.yml`](../.github/workflows/roblox_rank_sync.yml)
   - 负责统一注入运行环境变量
   - 负责执行 `python -m app.main`
   - 负责上传 artifacts
   - AI 代码审核使用独立工作流 [`/.github/workflows/ai_code_review.yml`](../.github/workflows/ai_code_review.yml)，不参与 Roblox 数据同步链路

3. Python 主程序
   - 文件：[`app/main.py`](../app/main.py)
   - 负责按 `RUN_REPORT_MODE` 分流
   - 负责抓 Roblox 数据
   - 负责写本地产物
   - 负责更新飞书表格与发送飞书消息

4. 飞书
   - 作为命令触发入口
   - 作为表格和消息展示端
   - 通过应用身份调用消息 API 与电子表格 API

5. GitHub Variables
   - 作为跨次运行的轻量持久化存储
   - 保存飞书表格 token、sheet id、Top Trending 历史排名

### 2.1 两种触发源

当前只有两种官方触发源：

1. 飞书群命令
   - Worker 收到事件
   - 校验来源
   - dispatch GitHub Actions
   - 先回一条“已提交任务”
   - 运行结束后 Python 回发最终结果

2. Cloudflare Cron
   - Worker 直接按 cron 分流到不同 `report_mode`
   - 不使用 GitHub Actions 自带 `schedule`
   - Top Trending 与项目日报统一发到 `SCHEDULE_CHAT_IDS`
   - 收入日报只发到 `ROBLOX_MONEY_TEST_CHAT_IDS`

## 3. 四条运行模式的真实行为

### 3.1 `top100_message`

入口：

- 默认本地运行
- GitHub Actions 手动触发，`report_mode=top100_message`
- 飞书命令 `/roblox-top100`

执行路径：

1. `app/main.py` 调用 `RobloxClient.fetch_top_games()`
2. `RobloxClient` 根据 `ROBLOX_SORT_ID` 决定榜单，默认 `top-playing-now`
3. 拉取榜单、游戏详情、本地化名称、缩略图
4. 写入 `data/top100_YYYY-MM-DD.json` 和 `data/top100_YYYY-MM-DD.csv`
5. 成功时不再发送飞书摘要消息，只保留本地产物更新；失败通知仍走飞书失败消息

配置要点：

- `ROBLOX_SORT_ID` 当前只对这个模式生效
- `ROBLOX_CREATOR_COOKIE` 在这个模式下不是强制必需，但建议配置，否则容易漏掉登录态可见内容
- 成功通知已关闭，`RUN_CHAT_ID` / `FEISHU_BOT_WEBHOOK` 只影响失败通知兜底

输出特点：

- 只写本地 JSON/CSV，不写飞书表格
- 成功文案不再发送；失败文案仍由 [`app/summary.py`](../app/summary.py) 生成

### 3.2 `top_trending_sheet`

入口：

- 飞书命令 `/roblox-top-day`
- Cloudflare Cron `0 1 * * *`

执行路径：

1. `app/main.py` 固定抓 4 个榜单：
   - `Top_Trending_V4`
   - `Up_And_Coming_V4`
   - `top-playing-now`
   - `top-earning`
2. 跳过缩略图请求，因为当前不再写飞书表格
3. 先按旧 GitHub Variables 计算最近 7 天历史上榜集合
4. 更新历史排名到 GitHub Variables
5. 发送 `今日关注` 飞书卡片
6. 只输出本地 JSON artifact，不再生成 CSV

这个模式的关键维护事实：

- 当前主流程没有使用 `ROBLOX_TOP_TRENDING_SORT_ID`
- 即使工作流里注入了 `ROBLOX_TOP_TRENDING_SORT_ID`，也不会改变这里实际抓取的 sort id
- 真正决定 sort id 的是 [`app/main.py`](../app/main.py) 里的硬编码分流
- `top-earning` 会通过 `pageToken` 尽量分页抓取前 300 名；如果 Roblox Explore 接口返回不足 300 条，则按实际返回记录；如果该榜单临时失败，本次会跳过收入榜历史排名更新，不阻断其他 3 个榜单和今日关注卡片
- 这个模式不再创建、更新或发送飞书表格链接；旧表格 token、sheet id 变量仅作为历史遗留配置保留

#### 正式和测试历史排名切换规则

Top Trending 维护了“正式”和“测试”两套历史排名变量。

切换规则仍复用 [`app/top_trending_sheet.py`](../app/top_trending_sheet.py)：

- 只有 `RUN_TRIGGER_SOURCE=cloudflare_cron` 时，才使用正式历史排名变量
- 其他触发源全部走测试历史排名变量

这意味着：

- 飞书手动命令 `/roblox-top-day` 默认读写测试历史排名
- GitHub Actions 页面手动 `Run workflow` 默认也读写测试历史排名
- 只有 Cloudflare 定时任务才会读写正式历史排名

如果有人说“我手动跑了 `/roblox-top-day`，怎么正式历史排名没变”，这通常不是 bug，而是当前设计使然。

#### 当前持久化的变量

正式历史排名变量：

- `FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_SHEET_ID`
- `FEISHU_UP_AND_COMING_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_SHEET_ID`
- `FEISHU_TOP_EARNING_SHEET_ID`
- `FEISHU_TOP_TRENDING_PREV_RANKS`
- `FEISHU_UP_AND_COMING_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_PREV_RANKS`
- `FEISHU_TOP_EARNING_PREV_RANKS`
- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`

测试历史排名变量：

- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_TEST_SHEET_ID`
- `FEISHU_UP_AND_COMING_TEST_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_TEST_SHEET_ID`
- `FEISHU_TOP_EARNING_TEST_SHEET_ID`
- `FEISHU_TOP_TRENDING_TEST_PREV_RANKS`
- `FEISHU_UP_AND_COMING_TEST_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_TEST_PREV_RANKS`
- `FEISHU_TOP_EARNING_TEST_PREV_RANKS`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

其中 spreadsheet token、sheet id、spreadsheet title 变量是旧飞书表格链路遗留配置；当前 Top Trending 主链路只读写 `*_PREV_RANKS` 历史排名变量。

#### 今日关注规则

`今日关注` 卡片由 [`app/top_trending_briefing.py`](../app/top_trending_briefing.py) 构建，当前规则是：

- 只关注“最近 7 天未进入同一个榜单，且首次上线未满 180 天（约 6 个月）”的游戏；这里的“未上榜”按榜单维度分别判断，不是跨 4 个榜单全局排除
- 聚合 4 个榜单后按游戏去重
- 优先显示排名更高的记录
- 最多显示 10 条
- 游戏名优先显示“英文名 + 中文名”
- 每个游戏的上榜来源单独另起一行展示，格式为 `新进榜单 | 当天其他命中榜单`
- 不同榜单标签使用不同颜色；其中 `收入榜` 最醒目且优先展示，`新秀榜` 次之，`热门榜` 使用绿色，`在玩榜` 使用灰色
- 示例：某游戏昨天首次进入新游/新秀榜，今天又首次进入 Top Earning，只要它此前 7 天没有进入过 Top Earning，今天仍会出现在 `今日关注` 中，并显示 `收入榜 #排名`

#### 历史表格代码状态

[`app/top_trending_sheet.py`](../app/top_trending_sheet.py) 仍保留旧飞书多 Sheet 的表格构建、样式和历史排名工具函数，当前主流程只复用其中的变量解析与历史排名读写能力。

Top Trending 主流程不再调用旧表格同步函数，不再写缩略图、列宽、行高、字体颜色、高亮或排名变化到飞书表格。

#### 产物注意点

这个模式只把 `top_trending_v4` 这一份榜单写成本地 JSON：

- `data/top_trending_YYYY-MM-DD.json`

如果未来需要把 4 个榜单都落盘，目前要改 [`app/main.py`](../app/main.py) 和 [`app/storage.py`](../app/storage.py)。

### 3.3 `roblox_project_daily_metrics`

入口：

- 飞书命令 `/roblox-project-metrics`
- Cloudflare Cron `10 1 * * *`

执行路径：

1. `app/main.py` 调用 `resolve_project_metrics_variables()`
2. 根据 `ROBLOX_CREATOR_OVERVIEW_URL`、`ROBLOX_CREATOR_OVERVIEW_URL_2` 和 `ROBLOX_CREATOR_OVERVIEW_URL_3` 解析需要抓取的项目
3. 逐个项目调用 `RobloxCreatorMetricsClient.fetch_project_daily_metrics()`
4. 按项目写各自的飞书表格
5. 将所有成功项目的数据合并写入本地 JSON/CSV
6. 对部分失败项目发送补充失败说明

如果 `ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT=true`，项目日报会临时跳过第二项目槽位 `ROBLOX_CREATOR_OVERVIEW_URL_2`。这只影响 `roblox_project_daily_metrics`：不抓取第二项目、不写第二项目飞书表、不在 `project_metrics_*.json/csv` 中输出第二项目记录，也不发送第二项目表格链接；`roblox_money` 收入日报默认使用第一项目和第三槽位的 `Troll ur friends`，不受该开关影响。当前 GitHub Actions workflow 未配置该变量时按 `true` 注入，默认不发送第二项目 Jail Ur Fiends 的日报表格；如需恢复第二项目日报，则在 GitHub Variables 中明确设为 `false`。

#### 当前项目日报能力边界

当前只支持最多 3 个项目，因为代码里只有三套配置槽位：

- `ROBLOX_CREATOR_OVERVIEW_URL`
- `ROBLOX_CREATOR_OVERVIEW_URL_2`
- `ROBLOX_CREATOR_OVERVIEW_URL_3`

以及对应三套飞书表变量：

- `FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_SHEET_ID`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_2_SHEET_ID`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_3_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_3_SHEET_ID`
- `FEISHU_PROJECT_METRICS_3_SPREADSHEET_TITLE`

如果要接第四个项目，必须同步修改：

- [`app/config.py`](../app/config.py)
- [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py)
- [`/.github/workflows/roblox_rank_sync.yml`](../.github/workflows/roblox_rank_sync.yml)
- 相关测试

#### 数据窗口与日期口径

项目日报的可查日期范围由 [`app/roblox_creator_metrics_client.py`](../app/roblox_creator_metrics_client.py) 决定，实际查询日期由 [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py) 根据旧表内容生成：

- 以业务时区午夜为界
- 默认范围是“项目起始日到昨天”
- 整体日期范围不会因为 `PeakConcurrentPlayers` 的 28 天保留期而截断，仍按项目起始日到昨天生成候选日期
- 实际查询按空单元格字段生成计划：已有日期行只回查仍为空的指标，已有非空单元格不会被新结果覆盖
- 如果某个历史日期只缺 `peak_ccu`，但该日期已超出 Roblox 当前可查保留期，本次会跳过该字段，避免重复请求已明确不可查的历史 PeakConcurrentPlayers
- 若没有已保存的飞书表目标，则按项目起始日到昨天补齐当前表格容量内的日期

当前项目起始日定义在 [`app/project_metrics_models.py`](../app/project_metrics_models.py)：

- `9682356542`：`2026-03-09`
- `9707829514`：`2026-03-17`
- `10170801715`：`2026-05-31`

#### 当前指标来源

项目日报当前主要直接走 Roblox Analytics Query Gateway：

- `PeakConcurrentPlayers`
- `AveragePlayTimeMinutesPerDAU`
- `DailyCohortRetention`
- `AverageRevenuePerUser`
- `PayingUsersCVR`
- `AverageRevenuePerPayingUser`
- `RFYQualifiedPTR`
- `TotalSessionsEndedInBucket`
- `UniqueUsersWithImpressions`
- `ClientCrashRate15m`
- `ClientMemoryUsageAvg`
- `ClientFpsAvg`
- `ServerCrashCount`
- `MemoryUsageAvg`（Creator Dashboard URL 中展示为 `ServerMemoryUsageV2`，前端会映射到该 API 指标）
- `ServerFrameRateAvg`

同时还会查询：

- `feature-permissions`
- `status-config`
- `metrics/metadata`

`metrics/metadata` 的作用很重要：

- 用于判断指标最新可用日期
- 用于过滤还未成熟的留存和 cohort 数据
- 避免把“未来还没产出”的空数据错误写进日报

#### 项目日报表格表现层规则

项目日报表包含 `ARPDAU` 列，数据来源为 Roblox Creator Analytics 的 `AverageRevenuePerUser` 日粒度指标。该列位于 `付费率` 前方，按货币格式写入，不参与同类排名字体颜色或加粗样式。

项目日报的同类排名列会按单元格内容中的数值部分设置字体颜色：

- `>= 90` 固定为深绿色
- `>= 50` 到 `< 90` 在浅绿色到深绿色之间渐变
- `>= 25` 到 `< 50` 在黄色到浅绿色之间渐变
- `>= 0` 到 `< 25` 在红色到黄色之间渐变

写表后会先把排名列字体重置为黑色，再把排名列数据区设置为加粗，最后对有有效数值的排名单元格应用渐变色，避免旧颜色残留到空白单元格。

#### 部分成功是允许的

项目日报模式允许“有的项目成功，有的项目失败”。

当前行为：

- 抓取阶段不因单个项目、单个日期或单个指标失败而中断
- 成功项目照常写表并回发链接
- 失败项目单独追加一条“项目日报抓取异常”通知
- 如果所有项目都失败，也会生成空 artifact 并发送失败摘要，不再让 GitHub Actions 因抓取失败变红
- 这个模式同样依赖飞书应用身份调用电子表格 API，只有 webhook 无法完成写表

#### 核心字段与调试快照

项目日报默认把 `peak_ccu` 视为核心字段：

- `9682356542` 等未特殊配置的项目，如果某个待写入日期缺少 `peak_ccu`，该项目本次会进入失败摘要，不会把缺峰值 PCU 的日报行静默写入表格。
- `9707829514` 当前在 Roblox analytics 接口中长期缺失 `PeakConcurrentPlayers`，因此显式放宽为不校验 `peak_ccu`，仍允许写入其他指标。
- 非核心指标缺失时仍会留空，并写出调试快照用于排查。

当项目日报缺少任意指标时，会在 `OUTPUT_DIR` 下按项目写出：

- `data/creator_overview_debug_<project_id>.json`

这个文件包含：

- 已抓到的指标
- 缺失字段列表
- 每次 direct query 的请求与响应摘录
- HTML/可见文本/脚本字段占位

当前项目日报主链路主要依赖 direct query，因此排查时优先看 `direct_query_attempts`，不要默认认为 HTML 片段一定有用。非核心指标缺失只会留空并写调试快照；核心字段缺失会让对应项目进入失败摘要，避免继续写入关键指标不完整的日期行。

### 3.4 `roblox_money`

入口：

- test 群命令 `/roblox-money`
- Cloudflare Cron `20 1 * * *`

执行路径：

1. Worker 校验命令来源群必须在 `ROBLOX_MONEY_TEST_CHAT_IDS`
2. `app/main.py` 调用收入日报项目解析逻辑，默认使用第一项目 overview URL 与第三槽位 `Troll ur friends`（`10170801715`）overview URL；如果第三槽位未配置，则兼容退回前两个项目 overview URL
3. `RobloxCreatorMetricsClient.fetch_project_revenue_series()` 查询 Creator Analytics 总收入候选指标
4. Python 侧按配置 `ROBLOX_MONEY_USD_PER_100K_ROBUX` 将 Robux 换算成美元
5. 发送收入日报飞书卡片，不创建或更新飞书表格
6. 输出 `data/roblox_money_YYYY-MM-DD.json/csv`

#### 收入口径

- 每日收入展示 Roblox Analytics 当前最新可用收入日期的一天收入，避免早上抓到尚未产出的日期
- 月累计按统计日所在自然月计算，从自然月 1 日累计到该统计日
- 2026 年 5 月因为功能起始日是 `2026-05-01`，所以本月累计从 `2026-05-01` 开始
- 后续月份自动从当月 1 日开始累计
- 不使用 `AverageRevenuePerPayingUser` / ARPPU 推算总收入
- 当前候选总收入指标顺序为 `Revenue`、`TotalRevenue`、`DailyRevenue`

#### test 群限制

`roblox_money` 与现有两个定时任务不同：

- 手动命令只允许 `ROBLOX_MONEY_TEST_CHAT_IDS` 里的群触发
- 定时消息也只发到 `ROBLOX_MONEY_TEST_CHAT_IDS`
- 它不复用 `SCHEDULE_CHAT_IDS`

## 4. 触发映射

### 4.1 飞书命令到运行模式

默认命令映射在 [`worker/src/index.js`](../worker/src/index.js)：

| 飞书命令 | 运行模式 |
| --- | --- |
| `/roblox-top100` | `top100_message` |
| `/roblox-top-day` | `top_trending_sheet` |
| `/roblox-project-metrics` | `roblox_project_daily_metrics` |
| `/roblox-money` | `roblox_money` |

当前是严格全字匹配，不支持模糊匹配。

Worker 允许通过环境变量改命令文本：

- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`
- `ROBLOX_MONEY_COMMAND_TEXT`

### 4.2 Cloudflare Cron 到运行模式

当前 cron 定义在 [`worker/wrangler.toml`](../worker/wrangler.toml)：

| Cron | 北京时间 | 运行模式 |
| --- | --- | --- |
| `0 1 * * *` | `09:00` | `top_trending_sheet` |
| `10 1 * * *` | `09:10` | `roblox_project_daily_metrics` |
| `20 1 * * *` | `09:20` | `roblox_money` |

定时 dispatch 逻辑在 [`worker/src/index.js`](../worker/src/index.js)。

注意：

- Top Trending 与项目日报复用同一个 `SCHEDULE_CHAT_IDS`
- `SCHEDULE_CHAT_IDS` 支持逗号分隔多个 `chat_id`
- 定时触发会把多个 `chat_id` 原样传入 `RUN_CHAT_ID`
- Python 侧会拆分后逐个群发送
- 收入日报定时只使用 `ROBLOX_MONEY_TEST_CHAT_IDS`，并且手动 `/roblox-money` 也只允许这些群触发

## 5. 配置到底放在哪里

### 5.1 GitHub Actions Secrets

当前 GitHub Actions 需要的核心 Secrets：

- `ROBLOX_CREATOR_COOKIE`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_WEBHOOK`
- `GH_TOKEN`
- `OPENAI_API_KEY`（仅 AI 自动代码审核工作流需要）

说明：

- `GH_TOKEN` 在工作流里会映射成 Python 侧的 `GITHUB_VARIABLES_TOKEN`
- 它的职责不是 dispatch workflow，而是给 Python 更新 GitHub Variables
- `OPENAI_API_KEY` 只供 [`/.github/workflows/ai_code_review.yml`](../.github/workflows/ai_code_review.yml) 调用 OpenAI Responses API，不应在业务同步工作流中注入

### 5.2 GitHub Actions Variables

### Top Trending 相关

当前 Top Trending 主链路只使用历史排名变量；spreadsheet token、sheet id、spreadsheet title 是旧表格链路遗留变量。

- `FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_SHEET_ID`
- `FEISHU_UP_AND_COMING_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_SHEET_ID`
- `FEISHU_TOP_EARNING_SHEET_ID`
- `FEISHU_TOP_TRENDING_PREV_RANKS`
- `FEISHU_UP_AND_COMING_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_PREV_RANKS`
- `FEISHU_TOP_EARNING_PREV_RANKS`
- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_TEST_SHEET_ID`
- `FEISHU_UP_AND_COMING_TEST_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_TEST_SHEET_ID`
- `FEISHU_TOP_EARNING_TEST_SHEET_ID`
- `FEISHU_TOP_TRENDING_TEST_PREV_RANKS`
- `FEISHU_UP_AND_COMING_TEST_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_TEST_PREV_RANKS`
- `FEISHU_TOP_EARNING_TEST_PREV_RANKS`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

### 项目日报相关

- `ROBLOX_CREATOR_OVERVIEW_URL`
- `ROBLOX_CREATOR_OVERVIEW_URL_2`
- `ROBLOX_CREATOR_OVERVIEW_URL_3`
- `ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT`，可选；当前 GitHub Actions 未配置时按 `true` 注入，默认跳过第二项目槽位；如需恢复第二项目日报则设为 `false`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_SHEET_ID`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_2_SHEET_ID`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_3_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_3_SHEET_ID`
- `FEISHU_PROJECT_METRICS_3_SPREADSHEET_TITLE`

当前 GitHub Actions 会在 `ROBLOX_CREATOR_OVERVIEW_URL_3` 未配置时默认注入 `Troll ur friends` 的 overview URL：`https://create.roblox.com/dashboard/creations/experiences/10170801715/overview`。

### 收入日报相关

- `ROBLOX_MONEY_START_DATE`，默认 `2026-05-01`
- `ROBLOX_MONEY_USD_PER_100K_ROBUX`，必填，用于 Robux 到美元换算

### AI 自动代码审核相关

- `OPENAI_REVIEW_MODEL`，可选，默认 `gpt-5.4-mini`
- `AI_REVIEW_MAX_DIFF_CHARS`，可选，默认 `120000`
- `AI_REVIEW_MAX_CONTEXT_CHARS`，可选，默认 `24000`
- `AI_REVIEW_MAX_OUTPUT_TOKENS`，可选，默认 `4000`
- `AI_REVIEW_FEISHU_CHAT_ID`，可选但建议配置，用于把审核结果发送到飞书 Test 对话窗

AI 审核配置说明见 [`docs/ai-code-review.zh-CN.md`](./ai-code-review.zh-CN.md)。

### 5.3 Cloudflare Worker Secrets / 环境变量

Worker 当前必需配置：

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE`
- `GH_REF`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`

常用可选配置：

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`
- `SCHEDULE_CHAT_IDS`
- `ROBLOX_MONEY_TEST_CHAT_IDS`
- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`
- `ROBLOX_MONEY_COMMAND_TEXT`
- `EVENT_DEDUP_TTL_SECONDS`
- `EVENT_DEDUP_KV_BINDING`

说明：

- Worker 里的 `GH_TOKEN` 是给 Worker 调 GitHub Dispatch API 用的
- 这和 GitHub Actions 里的 `GH_TOKEN` 可以是同一个，也可以不是
- 如果 `ALLOWED_CHAT_IDS` / `ALLOWED_OPEN_IDS` 留空，则默认放行所有群或用户

### 5.4 本地运行环境变量

本地 `.env.example` 只覆盖了最基础的榜单运行参数。

如果要在本地调试完整链路，还需要自行补齐：

- 飞书应用参数
- GitHub Variables token
- 项目日报 overview URL
- 项目日报飞书表格 token / sheet id
- 收入日报汇率 `ROBLOX_MONEY_USD_PER_100K_ROBUX`

## 6. 持久化与状态管理

### 6.1 本地文件产物

写盘逻辑在 [`app/storage.py`](../app/storage.py)。

按模式分别生成：

- `top100_YYYY-MM-DD.json/csv`
- `top_trending_YYYY-MM-DD.json`
- `project_metrics_YYYY-MM-DD.json/csv`
- `roblox_money_YYYY-MM-DD.json/csv`
- `creator_overview_debug_<project_id>.json`（仅项目日报缺关键指标时）

GitHub Actions 会上传：

- `roblox-top100-data`
- `project-metrics-data`（仅项目日报模式）

### 6.2 Top Trending 历史排名

Top Trending 历史排名保存在 GitHub Variables 中，当前结构是一个 JSON：

```json
{
  "history": [
    {
      "ranks": {
        "123": 1,
        "456": 2
      }
    }
  ]
}
```

维护要点：

- 当前只保留最近 7 次历史
- 新写入格式只保存 `ranks`，最近上榜集合由 `ranks` 的 key 推导；旧的 `place_ids` + `ranks` 格式仍兼容读取
- 单个 GitHub Actions Variable 不能超过 48KB；如果历史 payload 过大，会优先裁掉最老历史记录，避免收入榜 300 条历史写入失败
- 既用于“排名变化”计算
- 也用于“最近 7 天是否上过榜”判断

### 6.3 飞书表格目标

项目日报飞书表格 token 和 sheet id 会在首次创建后回写 GitHub Variables。

也就是说：

- 项目日报首次运行时可能会创建新表
- 后续运行默认复用旧表
- 如果删了 GitHub Variables 但没删飞书表，就会创建新的表并切换指向
- Top Trending 当前不再创建或更新飞书表格

### 6.4 Worker 事件去重

Worker 事件去重默认使用 Cloudflare KV：

- 绑定名默认 `EVENT_DEDUP_KV`
- 默认 TTL 为 600 秒

如果 KV 没配置：

- Worker 会退回内存 `Map`
- 在冷启动或实例切换时不能可靠去重

因此新环境部署时，KV namespace 不是“锦上添花”，而是建议同步建好。

## 7. 重要代码索引

### 主流程

- [`app/main.py`](../app/main.py)
  - 主入口
  - 模式分流
  - 成功/失败通知收口

- [`app/config.py`](../app/config.py)
  - 所有运行时配置的唯一入口

### 榜单链路

- [`app/roblox_client.py`](../app/roblox_client.py)
  - Roblox 榜单抓取
  - 登录态请求头
  - 排行榜、详情、本地化聚合；Top Trending 当前跳过缩略图请求

- [`app/top_trending_sheet.py`](../app/top_trending_sheet.py)
  - Top Trending 历史表格结构
  - 正式/测试历史排名切换
  - 历史排名读写

- [`app/top_trending_briefing.py`](../app/top_trending_briefing.py)
  - `今日关注` 卡片构建

### 项目日报链路

- [`app/roblox_creator_metrics_client.py`](../app/roblox_creator_metrics_client.py)
  - Creator Analytics 指标抓取
  - direct query / metadata / debug snapshot

- [`app/project_metrics_models.py`](../app/project_metrics_models.py)
  - 项目起始日
  - 核心字段要求

- [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py)
  - 项目日报表头
  - 合并与整表重建逻辑

### 收入日报链路

- [`app/roblox_money_models.py`](../app/roblox_money_models.py)
  - 收入日报数据结构
  - 汇率与起始日期配置解析

- [`app/roblox_money_summary.py`](../app/roblox_money_summary.py)
  - 收入日报飞书卡片构建

### 飞书与 GitHub

- [`app/feishu_client.py`](../app/feishu_client.py)
  - 飞书消息、卡片、电子表格 API

- [`app/github_client.py`](../app/github_client.py)
  - GitHub Variables 持久化

- [`scripts/ai_code_review.py`](../scripts/ai_code_review.py)
  - GitHub push 后自动代码审核
  - 读取 commit range diff、项目规范与维护上下文
  - 调用 OpenAI Responses API，并把结果写入 Actions Summary 与飞书 Test 对话窗

### 部署与桥接

- [`/.github/workflows/roblox_rank_sync.yml`](../.github/workflows/roblox_rank_sync.yml)
  - 工作流入口
  - 环境变量注入
  - artifact 上传

- [`worker/src/index.js`](../worker/src/index.js)
  - 飞书命令桥接
  - 定时桥接
  - 事件去重

- [`worker/wrangler.toml`](../worker/wrangler.toml)
  - Worker 名称
  - KV 绑定
  - 当前 cron

## 8. 常见维护动作

### 8.1 轮换 Roblox Cookie

什么时候要做：

- 项目日报全部失败
- 榜单里明显缺登录态内容
- `creator_overview_debug_<project_id>.json` 里只剩未登录页面壳
- GitHub Actions 日志出现 `401` / `403`

处理步骤：

1. 重新获取有效 `.ROBLOSECURITY`
2. 更新 GitHub Secret `ROBLOX_CREATOR_COOKIE`
3. 手动跑一次工作流验证

### 8.2 新增一个项目日报项目

如果只是修改现有三个项目，改变量即可。

如果要新增第四个项目，必须改代码：

1. 在 [`app/config.py`](../app/config.py) 增加新字段
2. 在工作流中增加对应环境变量注入
3. 在 [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py) 扩展变量解析
4. 在 [`app/project_metrics_models.py`](../app/project_metrics_models.py) 增加起始日期和必要字段策略
5. 补齐测试

### 8.3 调整 Top Trending 正式/测试历史排名策略

当前判断规则只看：

- `cfg.run_report_mode == "top_trending_sheet"`
- `cfg.run_trigger_source == "cloudflare_cron"`

如果以后想让飞书手动命令也读写正式历史排名，修改点在 [`app/top_trending_sheet.py`](../app/top_trending_sheet.py) 的 `_should_use_formal_sheet()`。

### 8.4 增加新的飞书命令

需要同步改动：

1. [`worker/src/index.js`](../worker/src/index.js) 的 `resolveCommand()`
2. [`app/main.py`](../app/main.py) 的模式分流
3. [`app/config.py`](../app/config.py) 的配置入口
4. 工作流输入与环境变量注入
5. 文档和测试

### 8.5 更换 Cloudflare 账号或新环境部署

除了配置 secrets，还要注意：

- [`worker/wrangler.toml`](../worker/wrangler.toml) 当前写死了一个 `EVENT_DEDUP_KV` namespace id
- 新账号必须先创建自己的 KV namespace
- 然后把 `wrangler.toml` 里的 `id` 改成新值再部署

如果忘了这一步，Worker 很可能无法在新环境里正确部署或正确去重。

### 8.6 启用 AI 自动代码审核

AI 自动代码审核不需要修改 Cloudflare Worker 或飞书配置。

启用步骤：

1. 在 GitHub Actions Secrets 中配置 `OPENAI_API_KEY`
2. 按需在 GitHub Actions Variables 中配置 `OPENAI_REVIEW_MODEL`
3. 在 GitHub Actions Variables 中配置 `AI_REVIEW_FEISHU_CHAT_ID`，建议填当前 Test 对话窗 `chat_id`
4. 向 `main` 分支 push 后，等待 `AI Code Review` 工作流在 Actions Summary 和飞书 Test 对话窗写入审核结果

该工作流不再绑定 Pull Request，也不再写 PR 评论。AI 审核发现风险只做通知，不作为提交阻断门禁。

## 9. 常见排查路径

### 9.1 飞书里发命令没有任何反应

先按这个顺序查：

1. Worker `/health` 是否正常
2. 飞书事件订阅 URL 是否校验通过
3. Worker 是否已部署最新版本
4. `FEISHU_VERIFICATION_TOKEN` 是否一致
5. `ALLOWED_CHAT_IDS` / `ALLOWED_OPEN_IDS` 是否误填

### 9.2 飞书收到“已提交任务”，但没有最终结果

优先排查：

1. GitHub Actions 是否真的启动
2. GitHub workflow 是否跑失败
3. `RUN_CHAT_ID` 是否被正确传入
4. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 是否有效
5. 最终发送阶段是否退回了 webhook 但 webhook 又不可用

### 9.3 `/roblox-top-day` 跑了，但读写的是测试历史排名

先确认触发源。

这通常是正常行为，因为：

- 手动命令默认就是测试历史排名
- 定时才是正式历史排名

### 9.4 Top Trending 没有飞书表格链接

当前这是预期行为。Top Trending 主链路只发送 `今日关注` 卡片，不再创建、更新或发送飞书表格链接。

### 9.5 项目日报列为空

按这个顺序查：

1. `project-metrics-data` artifact
2. `data/project_metrics_*.json`
3. `data/creator_overview_debug_<project_id>.json`
4. 对应项目是否被放宽了核心字段要求
5. `metrics/metadata` 是否显示该指标当天尚未成熟

### 9.6 榜单里缺游戏

优先检查：

1. `ROBLOX_CREATOR_COOKIE` 是否有效
2. [`app/roblox_client.py`](../app/roblox_client.py) 是否还在带 `Cookie`
3. Roblox 接口返回是否改了结构
4. 是否只是本地化名称请求失败，而非榜单本体失败；Top Trending 当前已经跳过缩略图请求

## 10. 每次改动后必须同步检查什么

发生下面这些变化时，必须同步更新本文件：

- 新增或删除 `report_mode`
- 飞书命令变化
- Cloudflare cron 变化
- Worker 环境变量变化
- GitHub Secrets / Variables 归属变化
- AI 代码审核工作流、模型、提示词或输入上下文变化
- 表格列结构变化
- Top Trending 今日关注或历史排名规则变化
- 项目日报指标口径变化
- 项目数量上限变化
- 正式 / 测试历史排名切换规则变化
- artifact 结构变化

如果某次改动会影响“新同事能否只靠文档就接手”，那它就一定需要更新这份文档。
