# 外部平台配置实操手册

这份手册面向“从零把 GitHub Actions、Cloudflare Worker、飞书三端接起来”的场景。

如果你先想理解项目整体架构和运行方式，先读：

- [`docs/maintenance-context.zh-CN.md`](./maintenance-context.zh-CN.md)

本文只关注“怎么把外部平台配置通”。

## 1. 你最终会搭出什么

配置完成后，链路会是这样：

1. 飞书群发送命令
2. Cloudflare Worker 接收飞书事件并校验
3. Worker 调 GitHub Actions `workflow_dispatch`
4. GitHub Actions 执行 `python -m app.main`
5. Python 程序抓取 Roblox 数据，更新飞书表格并回消息

同时，Cloudflare Cron 还会每天自动触发两条任务：

- `0 1 * * *` UTC：`top_trending_sheet`
- `10 1 * * *` UTC：`roblox_project_daily_metrics`

## 2. 准备信息

开始前先准备这些值：

- GitHub 仓库 owner
- GitHub 仓库名
- GitHub fine-grained token
- 飞书自建应用 `App ID`
- 飞书自建应用 `App Secret`
- 飞书事件订阅里的 `Verification Token`
- 目标飞书群 `chat_id`
- 可选的触发用户 `open_id`
- Roblox 登录态 `.ROBLOSECURITY`

## 3. 先验证 GitHub Actions 能独立跑通

不要一上来就连飞书和 Worker。先把 GitHub Actions 单独跑通。

### 3.1 推送代码

确认仓库里至少包含：

- [`/.github/workflows/roblox_rank_sync.yml`](../.github/workflows/roblox_rank_sync.yml)
- [`/worker`](../worker)

### 3.2 配置 GitHub Secrets

进入：

`Settings -> Secrets and variables -> Actions`

新增这些 Secrets：

- `ROBLOX_CREATOR_COOKIE`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_WEBHOOK`
- `GH_TOKEN`

说明：

- `ROBLOX_CREATOR_COOKIE`：填 `.ROBLOSECURITY`
- `FEISHU_BOT_WEBHOOK`：可选，用作消息兜底
- `GH_TOKEN`：给 Python 更新 GitHub Variables 用

### 3.3 配置 GitHub Variables

至少按你要启用的模式配置对应变量。

如果你要跑 Top Trending：

- `FEISHU_TOP_TRENDING_SPREADSHEET_TITLE`
- `FEISHU_TOP_TRENDING_TEST_SPREADSHEET_TITLE`

如果你要跑项目日报：

- `ROBLOX_CREATOR_OVERVIEW_URL`
- 可选：`ROBLOX_CREATOR_OVERVIEW_URL_2`
- `FEISHU_PROJECT_METRICS_SPREADSHEET_TITLE`
- 可选：`FEISHU_PROJECT_METRICS_2_SPREADSHEET_TITLE`

其余飞书表格 token / sheet id 可以留空，首次运行后由程序自动创建并回写。

### 3.4 手动跑一次工作流

进入：

`Actions -> Roblox Rank Sync -> Run workflow`

建议先试两个模式：

- `report_mode=top100_message`
- `report_mode=top_trending_sheet`

成功标准：

- 工作流状态为绿色
- 飞书能收到结果消息
- 如果是 `top_trending_sheet`，能创建或复用飞书表格

如果这一步没通，不要继续配置 Worker。

## 4. 配置 Cloudflare Worker

### 4.1 先处理 KV namespace

当前 [`worker/wrangler.toml`](../worker/wrangler.toml) 已经声明了：

- 绑定名：`EVENT_DEDUP_KV`

但其中的 namespace id 是当前环境值，不适合直接照搬到新账号。

新环境必须先在 Cloudflare 创建自己的 KV namespace，然后把 `worker/wrangler.toml` 里的 `id` 改成你的 namespace id。

不做这一步，事件去重很可能失效，甚至部署本身就会出问题。

### 4.2 安装并登录 Wrangler

```bash
cd worker
npm install
npx wrangler login
```

### 4.3 本地开发变量

如需本地调试 Worker，可以复制：

- [`worker/.dev.vars.example`](../worker/.dev.vars.example)

```bash
cd worker
cp .dev.vars.example .dev.vars
```

### 4.4 配置 Worker secrets

必需 secrets：

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE`
- `GH_REF`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`

常用可选值：

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`
- `SCHEDULE_CHAT_IDS`
- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`

### 方式 A：逐条执行

```bash
cd worker
npx wrangler secret put GH_TOKEN
npx wrangler secret put GH_OWNER
npx wrangler secret put GH_REPO
npx wrangler secret put GH_WORKFLOW_FILE
npx wrangler secret put GH_REF
npx wrangler secret put FEISHU_APP_ID
npx wrangler secret put FEISHU_APP_SECRET
npx wrangler secret put FEISHU_VERIFICATION_TOKEN
npx wrangler secret put ALLOWED_CHAT_IDS
npx wrangler secret put ALLOWED_OPEN_IDS
npx wrangler secret put SCHEDULE_CHAT_IDS
```

### 方式 B：使用仓库脚本

```bash
cd worker
powershell -ExecutionPolicy Bypass -File .\set-secrets.ps1
```

注意：

- 脚本不会设置 `SCHEDULE_CHAT_IDS`
- 所以如果要启用定时，脚本跑完后还要手动执行一次 `npx wrangler secret put SCHEDULE_CHAT_IDS`

### 4.5 部署 Worker

```bash
cd worker
npx wrangler deploy
```

部署成功后记下你的域名，例如：

`https://roblox-top100-feishu-trigger.<subdomain>.workers.dev`

### 4.6 健康检查

打开：

`https://你的-worker-域名/health`

预期返回：

```json
{"ok":true,"service":"feishu-gh-dispatch"}
```

## 5. 配置飞书自建应用

### 5.1 创建应用并开启机器人能力

在飞书开放平台创建“自建应用”，并启用机器人能力。

### 5.2 配置事件订阅

回调地址填：

`https://你的-worker-域名/feishu/events`

然后记录：

- `Verification Token`

这个值必须和 Worker 里的 `FEISHU_VERIFICATION_TOKEN` 一致。

### 5.3 订阅群文本消息相关事件

确保群内文本消息能投递到 Worker。

### 5.4 开通发消息和电子表格所需权限

至少要保证应用可以：

- 向群会话发消息
- 调用飞书电子表格 API

如果只配了 webhook，没有可用的飞书应用身份，那么：

- `top100_message` 还有机会通过 webhook 发摘要
- `top_trending_sheet` 和 `roblox_project_daily_metrics` 将无法创建或更新飞书表格

### 5.5 发布应用版本

不发布时，很多事件和权限不会真正生效。

### 5.6 把应用机器人拉进目标群

拉入后，它才能收到命令并回发结果。

## 6. 获取 `chat_id` 和 `open_id`

第一次联调时，建议先把下面两个限制留空：

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`

然后在目标群发送命令，去 Worker 日志里取值：

- `chat_id`
- `open_id`

拿到后再回填限制，最后重新部署 Worker。

## 7. 联调命令

当前默认支持 3 条命令：

```text
/roblox-top100
/roblox-top-day
/roblox-project-metrics
```

它们分别对应：

- `/roblox-top100` -> `top100_message`
- `/roblox-top-day` -> `top_trending_sheet`
- `/roblox-project-metrics` -> `roblox_project_daily_metrics`

联调时建议按这个顺序：

1. 先测 `/roblox-top100`
2. 再测 `/roblox-top-day`
3. 最后测 `/roblox-project-metrics`

### `/roblox-top-day` 特别注意

手动触发 `/roblox-top-day` 默认写测试表，不写正式表。

这是当前代码设计，不是异常。

## 8. 定时任务配置结果

当前定时由 Cloudflare Worker 负责，不使用 GitHub Actions 自带 `schedule`。

Worker 会按 [`worker/wrangler.toml`](../worker/wrangler.toml) 里的 cron 触发：

- `0 1 * * *` UTC：Top Trending
- `10 1 * * *` UTC：项目日报

两条定时任务都复用同一个：

- `SCHEDULE_CHAT_IDS`

如果 `SCHEDULE_CHAT_IDS` 为空：

- 这两个定时任务都会被 Worker 跳过

## 9. 推荐的完整验收顺序

1. GitHub 手动 `Run workflow` 成功
2. Worker `/health` 正常
3. 飞书事件 URL 校验成功
4. 飞书群发送 `/roblox-top100` 能触发并回结果
5. 飞书群发送 `/roblox-top-day` 能创建测试表并回链接
6. 飞书群发送 `/roblox-project-metrics` 能写项目日报表并回链接
7. 确认 `SCHEDULE_CHAT_IDS` 已配置
8. 等待或手动验证 cron 分支是否能触发

## 10. 排障顺序

如果外部平台没打通，按这个顺序查：

1. GitHub Actions 单独运行是否成功
2. Worker `/health` 是否正常
3. `worker/wrangler.toml` 中的 KV namespace id 是否是当前账号可用值
4. Worker secrets 是否完整
5. GitHub token 权限是否足够
6. 飞书应用是否已发布
7. 飞书机器人是否已入群
8. `ALLOWED_CHAT_IDS` / `ALLOWED_OPEN_IDS` 是否误填
9. `SCHEDULE_CHAT_IDS` 是否为空
