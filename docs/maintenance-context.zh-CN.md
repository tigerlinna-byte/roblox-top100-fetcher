# 项目维护上下文手册

这份文档用于帮助维护者在更换电脑、切换账号、长时间中断后，快速恢复项目上下文。

本文档以当前仓库代码为准，优先级高于旧 README、历史口头约定和外部截图。凡是涉及触发方式、配置变量、表格结构、定时策略、消息样式、数据口径的变动，都必须同步更新本文件。

## 1. 项目当前到底在做什么

这个仓库当前维护的是一套“Roblox 数据 -> GitHub Actions -> 飞书”的自动化链路，而不是一个单独的脚本。

当前有 3 条真实运行链路：

| 运行模式 | 入口 | 数据来源 | 结果 |
| --- | --- | --- | --- |
| `top100_message` | 本地运行、GitHub Actions 手动触发、飞书 `/roblox-top100` | Roblox 榜单接口 | 输出 JSON/CSV，并发送 Top100 文本摘要 |
| `top_trending_sheet` | 飞书 `/roblox-top-day`、Cloudflare Cron `0 1 * * *` | Roblox 榜单接口 | 更新 Top Trending 多 Sheet 飞书表，发送 `今日关注` 卡片和表格链接 |
| `roblox_project_daily_metrics` | 飞书 `/roblox-project-metrics`、Cloudflare Cron `10 1 * * *` | Roblox Creator Analytics 接口 | 更新每个项目自己的飞书表，并发送表格链接 |

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
   - 定时消息统一发到 `SCHEDULE_CHAT_IDS`

## 3. 三条运行模式的真实行为

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
5. 发送飞书 Markdown 摘要消息

配置要点：

- `ROBLOX_SORT_ID` 当前只对这个模式生效
- `ROBLOX_CREATOR_COOKIE` 在这个模式下不是强制必需，但建议配置，否则容易漏掉登录态可见内容
- 如果 `RUN_CHAT_ID` 有值且配置了 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，会按聊天 ID 发消息
- 如果没有 `RUN_CHAT_ID`，则退回 `FEISHU_BOT_WEBHOOK`

输出特点：

- 只发文本摘要，不写飞书表格
- 飞书文案由 [`app/summary.py`](../app/summary.py) 生成

### 3.2 `top_trending_sheet`

入口：

- 飞书命令 `/roblox-top-day`
- Cloudflare Cron `0 1 * * *`

执行路径：

1. `app/main.py` 固定抓 3 个榜单：
   - `Top_Trending_V4`
   - `Up_And_Coming_V4`
   - `top-playing-now`
2. 创建或复用飞书多 Sheet 表格
3. 按榜单分别写入 Sheet
4. 写缩略图、列宽、行高、颜色、高亮与排名变化
5. 更新历史排名到 GitHub Variables
6. 发送 `今日关注` 飞书卡片
7. 再单独发送飞书表格链接，触发表格预览

这个模式的关键维护事实：

- 当前主流程没有使用 `ROBLOX_TOP_TRENDING_SORT_ID`
- 即使工作流里注入了 `ROBLOX_TOP_TRENDING_SORT_ID`，也不会改变这里实际抓取的 sort id
- 真正决定 sort id 的是 [`app/main.py`](../app/main.py) 里的硬编码分流
- 这个模式依赖飞书应用身份调用电子表格 API，只有 webhook 不能替代 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`

#### 正式表和测试表切换规则

Top Trending 维护了“正式表”和“测试表”两套变量。

切换规则在 [`app/top_trending_sheet.py`](../app/top_trending_sheet.py)：

- 只有 `RUN_TRIGGER_SOURCE=cloudflare_cron` 时，才使用正式表变量
- 其他触发源全部走测试表变量

这意味着：

- 飞书手动命令 `/roblox-top-day` 默认写测试表
- GitHub Actions 页面手动 `Run workflow` 默认也写测试表
- 只有 Cloudflare 定时任务才会写正式表

如果有人说“我手动跑了 `/roblox-top-day`，怎么正式表没变”，这通常不是 bug，而是当前设计使然。

#### 当前持久化的变量

正式表变量：

- `FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_SHEET_ID`
- `FEISHU_UP_AND_COMING_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_SHEET_ID`
- `FEISHU_TOP_TRENDING_PREV_RANKS`
- `FEISHU_UP_AND_COMING_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_PREV_RANKS`
- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`

测试表变量：

- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_TEST_SHEET_ID`
- `FEISHU_UP_AND_COMING_TEST_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_TEST_SHEET_ID`
- `FEISHU_TOP_TRENDING_TEST_PREV_RANKS`
- `FEISHU_UP_AND_COMING_TEST_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_TEST_PREV_RANKS`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

#### 今日关注规则

`今日关注` 卡片由 [`app/top_trending_briefing.py`](../app/top_trending_briefing.py) 构建，当前规则是：

- 只关注“最近 7 天未上榜，且首次上线未满 90 天”的游戏
- 聚合 3 个榜单后去重
- 优先显示排名更高的记录
- 最多显示 10 条
- 游戏名优先显示“英文名 + 中文名”

#### 表格表现层规则

表格规则集中在 [`app/top_trending_sheet.py`](../app/top_trending_sheet.py)：

- Sheet 固定 3 个
- 每张表至少渲染 140 行
- 缩略图写在 B 列
- 排名变化写在 F 列
- 游戏名高亮写在 C 列
- 首次上线日期写在 I 列
- 首次上线 90 天内标绿，180 天内标黄，365 天以上标灰
- `进榜` 或排名上升标红，排名下降标绿

#### 产物注意点

虽然这个模式会更新 3 个 Sheet，但本地 JSON/CSV 产物当前只写 `top_trending_v4` 这一份榜单：

- `data/top_trending_YYYY-MM-DD.json`
- `data/top_trending_YYYY-MM-DD.csv`

如果未来需要把 3 个榜单都落盘，目前要改 [`app/main.py`](../app/main.py) 和 [`app/storage.py`](../app/storage.py)。

### 3.3 `roblox_project_daily_metrics`

入口：

- 飞书命令 `/roblox-project-metrics`
- Cloudflare Cron `10 1 * * *`

执行路径：

1. `app/main.py` 调用 `resolve_project_metrics_variables()`
2. 根据 `ROBLOX_CREATOR_OVERVIEW_URL` 和 `ROBLOX_CREATOR_OVERVIEW_URL_2` 解析需要抓取的项目
3. 逐个项目调用 `RobloxCreatorMetricsClient.fetch_project_daily_metrics()`
4. 按项目写各自的飞书表格
5. 将所有成功项目的数据合并写入本地 JSON/CSV
6. 对部分失败项目发送补充失败说明

#### 当前项目日报能力边界

当前只支持最多 2 个项目，因为代码里只有两套配置槽位：

- `ROBLOX_CREATOR_OVERVIEW_URL`
- `ROBLOX_CREATOR_OVERVIEW_URL_2`

以及对应两套飞书表变量：

- `FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_SHEET_ID`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_2_SHEET_ID`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TITLE`

如果要接第三个项目，必须同步修改：

- [`app/config.py`](../app/config.py)
- [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py)
- [`/.github/workflows/roblox_rank_sync.yml`](../.github/workflows/roblox_rank_sync.yml)
- 相关测试

#### 数据窗口与日期口径

项目日报的查询窗口由 [`app/roblox_creator_metrics_client.py`](../app/roblox_creator_metrics_client.py) 决定：

- 以业务时区午夜为界
- 默认抓“最近 10 天，截止到昨天”
- 若项目起始日更晚，则从项目起始日开始

当前项目起始日定义在 [`app/project_metrics_models.py`](../app/project_metrics_models.py)：

- `9682356542`：`2026-03-09`
- `9707829514`：`2026-03-17`

#### 当前指标来源

项目日报当前主要直接走 Roblox Analytics Query Gateway：

- `PeakConcurrentPlayers`
- `AveragePlayTimeMinutesPerDAU`
- `DailyCohortRetention`
- `PayingUsersCVR`
- `AverageRevenuePerPayingUser`
- `RFYQualifiedPTR`
- `TotalSessionsEndedInBucket`
- `UniqueUsersWithImpressions`
- `ClientCrashRate15m`
- `ClientMemoryUsageAvg`
- `ClientFpsAvg`
- `ServerCrashCount`
- `ServerMemoryUsageAvg`
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

项目日报的同类排名列会按单元格内容中的数值部分设置字体颜色：

- `>= 90` 固定为深绿色
- `>= 50` 到 `< 90` 在浅绿色到深绿色之间渐变
- `>= 25` 到 `< 50` 在黄色到浅绿色之间渐变
- `>= 0` 到 `< 25` 在红色到黄色之间渐变

写表后会先把排名列字体重置为黑色，再把排名列数据区设置为加粗，最后对有有效数值的排名单元格应用渐变色，避免旧颜色残留到空白单元格。

#### 部分成功是允许的

项目日报模式允许“有的项目成功，有的项目失败”。

当前行为：

- 只要至少有一个项目抓取成功，整个任务就算成功
- 成功项目照常写表并回发链接
- 失败项目单独追加一条“部分项目抓取失败”通知
- 如果所有项目都失败，则整个任务报错
- 这个模式同样依赖飞书应用身份调用电子表格 API，只有 webhook 无法完成写表

#### 核心字段放宽规则

项目 `9707829514` 当前对核心字段校验做了放宽。

原因写在 [`app/project_metrics_models.py`](../app/project_metrics_models.py)：

- 该项目长期缺失 `PeakConcurrentPlayers`
- 如果仍然强制校验 `peak_ccu`，就会让这个项目长期处于失败状态

当前配置是：

- 默认项目必须至少拿到 `peak_ccu`
- `9707829514` 例外，不要求核心字段

后续如果 Roblox 接口恢复了这个指标，记得把放宽逻辑收回去。

#### 调试快照

当项目日报缺少核心指标时，会在 `OUTPUT_DIR` 下写出：

- `data/creator_overview_debug.json`

这个文件包含：

- 已抓到的指标
- 缺失字段列表
- 每次 direct query 的请求与响应摘录
- HTML/可见文本/脚本字段占位

当前项目日报主链路主要依赖 direct query，因此排查时优先看 `direct_query_attempts`，不要默认认为 HTML 片段一定有用。

## 4. 触发映射

### 4.1 飞书命令到运行模式

默认命令映射在 [`worker/src/index.js`](../worker/src/index.js)：

| 飞书命令 | 运行模式 |
| --- | --- |
| `/roblox-top100` | `top100_message` |
| `/roblox-top-day` | `top_trending_sheet` |
| `/roblox-project-metrics` | `roblox_project_daily_metrics` |

当前是严格全字匹配，不支持模糊匹配。

Worker 允许通过环境变量改命令文本：

- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`

### 4.2 Cloudflare Cron 到运行模式

当前 cron 定义在 [`worker/wrangler.toml`](../worker/wrangler.toml)：

| Cron | 北京时间 | 运行模式 |
| --- | --- | --- |
| `0 1 * * *` | `09:00` | `top_trending_sheet` |
| `10 1 * * *` | `09:10` | `roblox_project_daily_metrics` |

定时 dispatch 逻辑在 [`worker/src/index.js`](../worker/src/index.js)。

注意：

- 这两个定时任务都复用同一个 `SCHEDULE_CHAT_IDS`
- `SCHEDULE_CHAT_IDS` 支持逗号分隔多个 `chat_id`
- 定时触发会把多个 `chat_id` 原样传入 `RUN_CHAT_ID`
- Python 侧会拆分后逐个群发送

## 5. 配置到底放在哪里

### 5.1 GitHub Actions Secrets

当前 GitHub Actions 需要的核心 Secrets：

- `ROBLOX_CREATOR_COOKIE`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_WEBHOOK`
- `GH_TOKEN`

说明：

- `GH_TOKEN` 在工作流里会映射成 Python 侧的 `GITHUB_VARIABLES_TOKEN`
- 它的职责不是 dispatch workflow，而是给 Python 更新 GitHub Variables

### 5.2 GitHub Actions Variables

### Top Trending 相关

- `FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_SHEET_ID`
- `FEISHU_UP_AND_COMING_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_SHEET_ID`
- `FEISHU_TOP_TRENDING_PREV_RANKS`
- `FEISHU_UP_AND_COMING_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_PREV_RANKS`
- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_TEST_SHEET_ID`
- `FEISHU_UP_AND_COMING_TEST_SHEET_ID`
- `FEISHU_TOP_PLAYING_NOW_TEST_SHEET_ID`
- `FEISHU_TOP_TRENDING_TEST_PREV_RANKS`
- `FEISHU_UP_AND_COMING_TEST_PREV_RANKS`
- `FEISHU_TOP_PLAYING_NOW_TEST_PREV_RANKS`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

### 项目日报相关

- `ROBLOX_CREATOR_OVERVIEW_URL`
- `ROBLOX_CREATOR_OVERVIEW_URL_2`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_SHEET_ID`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_2_SHEET_ID`
- `FEISHU_PROJECT_METRICS_2_SPREADSHEET_TITLE`

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
- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`
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
- 各类飞书表格 token / sheet id

## 6. 持久化与状态管理

### 6.1 本地文件产物

写盘逻辑在 [`app/storage.py`](../app/storage.py)。

按模式分别生成：

- `top100_YYYY-MM-DD.json/csv`
- `top_trending_YYYY-MM-DD.json/csv`
- `project_metrics_YYYY-MM-DD.json/csv`
- `creator_overview_debug.json`（仅项目日报缺关键指标时）

GitHub Actions 会上传：

- `roblox-top100-data`
- `project-metrics-data`（仅项目日报模式）

### 6.2 Top Trending 历史排名

Top Trending 历史排名保存在 GitHub Variables 中，当前结构是一个 JSON：

```json
{
  "history": [
    {
      "place_ids": [123, 456],
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
- 既用于“排名变化”计算
- 也用于“最近 7 天是否上过榜”判断

### 6.3 飞书表格目标

飞书表格 token 和 sheet id 会在首次创建后回写 GitHub Variables。

也就是说：

- 首次运行时可能会创建新表
- 后续运行默认复用旧表
- 如果删了 GitHub Variables 但没删飞书表，就会创建新的表并切换指向

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
  - 排行榜、详情、本地化、缩略图聚合

- [`app/top_trending_sheet.py`](../app/top_trending_sheet.py)
  - Top Trending 表格结构
  - 正式/测试表切换
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

### 飞书与 GitHub

- [`app/feishu_client.py`](../app/feishu_client.py)
  - 飞书消息、卡片、电子表格 API

- [`app/github_client.py`](../app/github_client.py)
  - GitHub Variables 持久化

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
- `creator_overview_debug.json` 里只剩未登录页面壳
- GitHub Actions 日志出现 `401` / `403`

处理步骤：

1. 重新获取有效 `.ROBLOSECURITY`
2. 更新 GitHub Secret `ROBLOX_CREATOR_COOKIE`
3. 手动跑一次工作流验证

### 8.2 新增一个项目日报项目

如果只是修改现有两个项目，改变量即可。

如果要新增第三个项目，必须改代码：

1. 在 [`app/config.py`](../app/config.py) 增加新字段
2. 在工作流中增加对应环境变量注入
3. 在 [`app/project_metrics_sheet.py`](../app/project_metrics_sheet.py) 扩展变量解析
4. 在 [`app/project_metrics_models.py`](../app/project_metrics_models.py) 增加起始日期和必要字段策略
5. 补齐测试

### 8.3 调整 Top Trending 正式/测试表策略

当前判断规则只看：

- `cfg.run_report_mode == "top_trending_sheet"`
- `cfg.run_trigger_source == "cloudflare_cron"`

如果以后想让飞书手动命令也写正式表，修改点在 [`app/top_trending_sheet.py`](../app/top_trending_sheet.py) 的 `_should_use_formal_sheet()`。

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

### 9.3 `/roblox-top-day` 跑了，但看到的是测试表

先确认触发源。

这通常是正常行为，因为：

- 手动命令默认就是测试表
- 定时才是正式表

### 9.4 Top Trending 表格标题异常或被写空

优先检查：

- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

代码会主动调用更新标题 API，所以不要把标题变量留空。

### 9.5 项目日报列为空

按这个顺序查：

1. `project-metrics-data` artifact
2. `data/project_metrics_*.json`
3. `data/creator_overview_debug.json`
4. 对应项目是否被放宽了核心字段要求
5. `metrics/metadata` 是否显示该指标当天尚未成熟

### 9.6 榜单里缺游戏

优先检查：

1. `ROBLOX_CREATOR_COOKIE` 是否有效
2. [`app/roblox_client.py`](../app/roblox_client.py) 是否还在带 `Cookie`
3. Roblox 接口返回是否改了结构
4. 是否只是缩略图或本地化名称请求失败，而非榜单本体失败

## 10. 每次改动后必须同步检查什么

发生下面这些变化时，必须同步更新本文件：

- 新增或删除 `report_mode`
- 飞书命令变化
- Cloudflare cron 变化
- Worker 环境变量变化
- GitHub Secrets / Variables 归属变化
- 表格列结构变化
- Top Trending 高亮规则变化
- 项目日报指标口径变化
- 项目数量上限变化
- 正式表 / 测试表切换规则变化
- artifact 结构变化

如果某次改动会影响“新同事能否只靠文档就接手”，那它就一定需要更新这份文档。
