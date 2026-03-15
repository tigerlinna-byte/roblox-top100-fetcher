# 项目维护上下文手册

这份文档用于帮助维护者在更换电脑或长时间中断后，快速恢复这个项目的上下文。

当前内容以仓库 `main` 分支现状为准。任何影响流程、配置、定时、消息样式、数据口径的改动，都必须同步更新本文件。

## 1. 项目目的

这个项目当前有两条核心业务链路：

1. `Roblox Top 100 / Trending` 榜单链路
   - 抓取 Roblox 榜单数据
   - 写入飞书普通表格
   - 向飞书群发送 `今日关注` 简报和榜单表格预览

2. `Shoot Or Shot` 项目日报链路
   - 抓取 Roblox Creator Analytics 内部指标
   - 写入飞书普通表格
   - 将结果发送到同一个飞书群

## 2. 整体架构

整体分 4 层：

1. Cloudflare Worker
   - 接收飞书消息回调
   - 接收 Cloudflare Cron Trigger
   - 调 GitHub Actions `workflow_dispatch`

2. GitHub Actions
   - 执行 Python 主程序 `python -m app.main`
   - 注入 Roblox / Feishu / GitHub 相关配置
   - 产出运行 artifacts

3. Python 主程序
   - 根据 `RUN_REPORT_MODE` 执行不同链路
   - 抓 Roblox 数据
   - 更新飞书表
   - 回发飞书消息

4. 飞书
   - 作为手动触发入口
   - 作为结果表格和结果消息的展示端

## 3. 当前两条业务链路

### 3.1 Top100 / Trending 链路

用途：

- 手动触发 `/roblox-top-day`
- Cloudflare 定时自动触发
- 更新飞书 Top Trending 多 Sheet 表格
- 在群里发送简报和表格预览

当前行为：

- 榜单抓取使用 `ROBLOX_CREATOR_COOKIE` 登录态，避免漏掉年龄限制游戏
- 成功后发送两条消息：
  1. `今日关注` 飞书卡片
  2. 单独发送飞书表格 URL，用于触发表格预览

`今日关注` 简报规则：

- 只关注“新上榜且首次上线未满 3 个月”的游戏
- 游戏名显示为：英文名 + 中文名
- 显示：
  - 游戏名
  - 上榜榜单 + 排名
  - 当前 CCU
  - 首次上线日期
- 如果值得关注的游戏超过 10 个：
  - 只显示前 10 个
  - 末尾提示“其余值得关注的游戏请直接查看下方表格。”

当前榜单包含 3 个 Sheet：

- `top_trending_v4`
- `up_and_coming_v4`
- `top_playing_now`

### 3.2 Shoot Or Shot 项目日报链路

用途：

- 手动触发 `/roblox-project-metrics`
- Cloudflare 定时自动触发
- 更新 `Shoot Or Shot` 飞书表
- 在群里发送表格链接

当前数据口径重点：

- 起始日期从 `2026-03-09` 开始
- 按真实数据日期写入表格
- 保留历史数据
- 每次重建数据区时会覆盖固定范围，避免旧残留数据

当前已对齐的重要指标：

- `峰值PCU`：来自 `PeakConcurrentPlayers / Daily`
- `平均在线时长`：来自 `AveragePlayTimeMinutesPerDAU / Daily`
- `次留 / 7留`：来自 `DailyCohortRetention + CohortDay`
- `五分钟留存`：来自 `Engagement` 分桶推导
- `Home Recommendation`：来自 `UniqueUsersWithImpressions + AcquisitionSource`
- `报错率`：来自 `ClientCrashRate15m / Daily`

## 4. 触发方式

### 4.1 飞书手动触发

当前支持：

- `/roblox-top100`
- `/roblox-top-day`
- `/roblox-project-metrics`

链路：

1. 飞书群消息进入 Cloudflare Worker
2. Worker 校验群和用户
3. Worker dispatch GitHub Actions
4. GitHub Actions 执行 Python
5. Python 写飞书表并回发消息

### 4.2 Cloudflare 定时触发

当前只由 Cloudflare Worker 负责定时，不使用 GitHub Actions `schedule`。

配置位置：

- [worker/wrangler.toml](C:/Users/41539/Desktop/roblox-top100-fetcher/worker/wrangler.toml)

当前 cron：

- `0 1 * * *`
  - Top100 / Trending
- `25 19 * * *`
  - Shoot Or Shot 项目日报
  - 北京时间 `03:25`

Worker 分流位置：

- [worker/src/index.js](C:/Users/41539/Desktop/roblox-top100-fetcher/worker/src/index.js)

## 5. GitHub Actions 工作流

工作流文件：

- [.github/workflows/roblox_rank_sync.yml](C:/Users/41539/Desktop/roblox-top100-fetcher/.github/workflows/roblox_rank_sync.yml)

当前设计：

- 只保留 `workflow_dispatch`
- 不使用 `schedule`
- 所有定时都由 Cloudflare Worker 触发

关键输入：

- `report_mode`
- `trigger_source`
- `trigger_actor`
- `chat_id`

主要运行环境变量：

- `RUN_REPORT_MODE`
- `RUN_TRIGGER_SOURCE`
- `RUN_TRIGGER_ACTOR`
- `RUN_CHAT_ID`

Artifacts：

- `roblox-top100-data`
- `project-metrics-data`

## 6. 配置放在哪里

### 6.0 Roblox 登录态方式

当前 Roblox 登录态不是通过账号密码实时登录，也不是通过 Open Cloud token。

当前项目使用的是：

- `ROBLOX_CREATOR_COOKIE`

这个配置里保存的是：

- `.ROBLOSECURITY` cookie

也就是说，当前整套 Roblox 抓取能力是基于“已登录浏览器会话”的 cookie 在工作，而不是用户名密码登录。

当前复用范围：

- Top100 / Trending 榜单抓取
- Shoot Or Shot 项目日报抓取

这两条链路当前都复用同一份 `ROBLOX_CREATOR_COOKIE`。

维护上必须知道的几点：

1. 改密码不一定会立刻让自动化失效
   - 真正决定能不能继续跑的是 `.ROBLOSECURITY` 是否还有效

2. Roblox 可能轮换 cookie
   - 如果 Roblox 服务端返回新的 `Set-Cookie`，当前这套实现默认不会自动持久化回 GitHub Secret，除非后续专门补这条能力

3. 这份 cookie 失效后，Top100 和项目日报会同时受影响
   - 因为它们共用一份登录态

### 6.1 GitHub Secrets

主要包含敏感信息：

- `ROBLOX_CREATOR_COOKIE`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_WEBHOOK`
- `GH_TOKEN`

### 6.2 GitHub Variables

主要包含可公开配置：

- `ROBLOX_CREATOR_OVERVIEW_URL`
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
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TOKEN`
- `FEISHU_PROJECT_METRICS_SHEET_ID`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`

### 6.3 Cloudflare Worker Secrets

Cloudflare 里维护：

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE`
- `GH_REF`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`
- `SCHEDULE_CHAT_IDS`

`SCHEDULE_CHAT_IDS` 很重要：

- Top100 定时发送依赖它
- Shoot Or Shot 定时也复用它
- 两条定时消息发送到同一个飞书群

## 7. 核心文件索引

### Python 主流程

- [app/main.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/main.py)
  - 主入口
  - 根据 `RUN_REPORT_MODE` 分流

### Top100 榜单

- [app/roblox_client.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/roblox_client.py)
  - Roblox 榜单抓取
  - 当前已接入登录态

- [app/top_trending_sheet.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/top_trending_sheet.py)
  - Top Trending 飞书表结构
  - 排名变化、首次上线颜色等

- [app/top_trending_briefing.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/top_trending_briefing.py)
  - 今日关注简报
  - 多榜合并
  - 卡片内容构建

### 项目日报

- [app/roblox_creator_metrics_client.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/roblox_creator_metrics_client.py)
  - Creator Analytics 指标抓取

- [app/project_metrics_models.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/project_metrics_models.py)
  - 项目日报模型

- [app/project_metrics_sheet.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/project_metrics_sheet.py)
  - 项目日报表头和重建逻辑

### 飞书和 GitHub

- [app/feishu_client.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/feishu_client.py)
  - 飞书文本消息
  - 飞书卡片消息
  - 飞书表格 API

- [app/github_client.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/github_client.py)
  - GitHub Variables 持久化

### Cloudflare Worker

- [worker/src/index.js](C:/Users/41539/Desktop/roblox-top100-fetcher/worker/src/index.js)
  - 飞书消息入口
  - 定时 dispatch 分流

- [worker/wrangler.toml](C:/Users/41539/Desktop/roblox-top100-fetcher/worker/wrangler.toml)
  - Cloudflare cron 配置

## 8. 常见排查路径

### 8.1 Top100 榜单缺游戏

优先检查：

- 是否带了 `ROBLOX_CREATOR_COOKIE`
- `ROBLOX_CREATOR_COOKIE` 是否仍然有效
- [app/roblox_client.py](C:/Users/41539/Desktop/roblox-top100-fetcher/app/roblox_client.py) 是否仍在发送 `Cookie`
- GitHub Actions 日志中榜单抓取是否报 `401/403`

### 8.2 项目日报有列为空

优先检查 artifacts：

- `project-metrics-data`
  - `data/project_metrics_*.json`
  - `data/project_metrics_*.csv`
  - `data/creator_overview_debug.json`

先判断空值发生在：

- 抓取层
- 导出层
- 还是飞书写表层

### 8.3 定时成功但群里没消息

优先检查：

- `SCHEDULE_CHAT_IDS`
- Cloudflare Worker 日志
- GitHub Actions 是否带上 `RUN_CHAT_ID`

过去出现过的根因：

- 项目日报 scheduled 分支没有传 `chat_id`
- 导致没有走原来稳定的应用消息发送链路

### 8.4 Roblox cookie 失效排查

优先看：

- GitHub Actions 日志
- `project-metrics-data` 或 `roblox-top100-data` artifact
- `data/creator_overview_debug.json`

常见表现：

- Roblox 接口返回 `401` 或 `403`
- `creator_overview_debug.json` 里只剩未登录壳页面
- Top100 榜单数量明显变少，尤其是年龄限制游戏消失
- Shoot Or Shot 页面返回 skeleton / 空数据

处理方式：

1. 重新获取新的 `.ROBLOSECURITY`
2. 更新 GitHub Secret `ROBLOX_CREATOR_COOKIE`
3. 再手动跑一次 workflow 验证

### 8.5 表格标题异常

Top100 正式表和测试表是两套标题变量：

- 正式表：
  - `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`
- 测试表：
  - `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

如果正式表标题变量为空，而代码又实际调用了更新标题 API，就会把正式表标题写空。

## 9. 运行和部署

### 9.1 本地运行 Python

```powershell
python -m app.main
```

### 9.2 本地运行测试

```powershell
python -m unittest discover -s tests
```

### 9.3 部署 Cloudflare Worker

```powershell
cd worker
npx wrangler deploy
```

注意：

- 只推 GitHub 代码不会更新 Cloudflare 线上 cron
- Worker 有任何改动后，都要重新部署

## 10. 维护规则

以后每次改动，以下类型的变化必须同步更新本文件：

- 触发方式变化
- Cloudflare cron 变化
- GitHub Actions 变化
- 飞书消息样式变化
- 表格结构变化
- Roblox 指标口径变化
- 配置项增加、删除、改名
- Secret / Variable 归属变化
- 排查路径变化

如果只是纯测试代码变动且不影响行为，可以不更新本文件。
