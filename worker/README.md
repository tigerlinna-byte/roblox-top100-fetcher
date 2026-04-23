# Feishu Trigger Worker

这个 Worker 负责把飞书群命令和 Cloudflare Cron 转成 GitHub Actions `workflow_dispatch`。

它的角色只有两个：

1. 接飞书事件并转发到 GitHub Actions
2. 接定时任务并转发到 GitHub Actions

项目整体维护说明请优先看：

- [`../docs/maintenance-context.zh-CN.md`](../docs/maintenance-context.zh-CN.md)

## 路由

- `GET /health`
- `POST /feishu/events`

## 默认命令映射

| 命令 | report mode |
| --- | --- |
| `/roblox-top100` | `top100_message` |
| `/roblox-top-day` | `top_trending_sheet` |
| `/roblox-project-metrics` | `roblox_project_daily_metrics` |

命令文本可以通过这些 Worker 环境变量覆盖：

- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `PROJECT_METRICS_COMMAND_TEXT`

## 必需配置

### 必需 secrets

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE`
- `GH_REF`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`

### 常用可选配置

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`
- `SCHEDULE_CHAT_IDS`
- `EVENT_DEDUP_TTL_SECONDS`
- `EVENT_DEDUP_KV_BINDING`

## 事件去重

当前默认使用 Cloudflare KV 做飞书事件去重：

- 默认绑定名：`EVENT_DEDUP_KV`
- 默认 TTL：`600` 秒

如果 KV 未配置，代码会退回进程内 `Map`，只能做弱去重，不适合作为正式环境方案。

## 当前定时任务

[`worker/wrangler.toml`](./wrangler.toml) 当前配置了两个 cron：

| Cron | 北京时间 | report mode |
| --- | --- | --- |
| `0 1 * * *` | `09:00` | `top_trending_sheet` |
| `10 1 * * *` | `09:10` | `roblox_project_daily_metrics` |

注意：

- 两个定时任务都依赖 `SCHEDULE_CHAT_IDS`
- 如果 `SCHEDULE_CHAT_IDS` 为空，定时任务会被跳过

## 本地测试

```bash
cd worker
node --test
```

## 本地调试

```bash
cd worker
cp .dev.vars.example .dev.vars
```

然后补齐 `.dev.vars` 中的值。

## 部署

```bash
cd worker
npm install
npx wrangler login
npx wrangler deploy
```

部署前请确认：

- `wrangler.toml` 里的 `EVENT_DEDUP_KV` namespace id 是当前 Cloudflare 账号可用值
- 必需 secrets 已写入
- 飞书回调地址已指向线上 Worker 域名
