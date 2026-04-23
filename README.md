# Roblox Top100 Fetcher

这个仓库当前不是单一的 Top100 抓取脚本，而是一套将 Roblox 榜单和项目指标同步到飞书的自动化系统。

## 当前支持的运行模式

| `RUN_REPORT_MODE` | 典型触发方式 | 主要行为 | 主要输出 |
| --- | --- | --- | --- |
| `top100_message` | 手动本地运行、GitHub Actions 手动触发、飞书 `/roblox-top100` | 抓取 `top-playing-now` 榜单并发送文本摘要 | `data/top100_YYYY-MM-DD.json/csv` + 飞书摘要消息 |
| `top_trending_sheet` | 飞书 `/roblox-top-day`、Cloudflare Cron | 抓取 `Top_Trending_V4`、`Up_And_Coming_V4`、`top-playing-now`，更新飞书多 Sheet 表格并发送 `今日关注` 卡片 | `data/top_trending_YYYY-MM-DD.json/csv` + 飞书卡片 + 飞书表格链接 |
| `roblox_project_daily_metrics` | 飞书 `/roblox-project-metrics`、Cloudflare Cron | 抓取 Roblox Creator Analytics 项目日报，更新每个项目各自的飞书表格 | `data/project_metrics_YYYY-MM-DD.json/csv` + 每个项目的飞书表格链接 |

## 系统结构

1. 飞书群命令或 Cloudflare Cron 进入 [worker/src/index.js](./worker/src/index.js)。
2. Worker 校验来源、做事件去重，然后调用 GitHub Actions `workflow_dispatch`。
3. GitHub Actions 执行 [app/main.py](./app/main.py)。
4. Python 主程序根据 `RUN_REPORT_MODE` 分流，抓取 Roblox 数据、更新飞书、写本地产物。
5. GitHub Variables 持久化飞书表格 token、sheet id 和 Top Trending 历史排名。

## 需要先知道的几个关键事实

- `top_trending_sheet` 模式在主流程里使用的是固定 sort id，分别是 `Top_Trending_V4`、`Up_And_Coming_V4`、`top-playing-now`。
- `ROBLOX_TOP_TRENDING_SORT_ID` 这个环境变量目前没有被主流程消费，不要把它当作 `/roblox-top-day` 的真实开关。
- `/roblox-top-day` 的手动触发默认写“测试表”，只有 `trigger_source=cloudflare_cron` 时才会写“正式表”。
- 项目日报当前只支持两个项目入口：`ROBLOX_CREATOR_OVERVIEW_URL` 和 `ROBLOX_CREATOR_OVERVIEW_URL_2`。如果要接第三个项目，需要改代码和工作流，不是只加变量就够。
- `ROBLOX_CREATOR_COOKIE` 对项目日报是必需项；对榜单链路虽然不是硬性必需，但没有它时容易漏掉需要登录态才能看到的游戏。

## 本地快速开始

1. 创建并激活虚拟环境。
2. 安装依赖：

```bash
python -m pip install -r requirements.txt
```

3. 复制环境变量模板：

```bash
cp .env.example .env
```

4. 根据要运行的模式补齐环境变量。
5. 执行一次主程序：

```bash
python -m app.main
```

## 运行测试

Python 测试：

```bash
python -m unittest discover -s tests
```

Worker 测试：

```bash
cd worker
node --test
```

## 部署入口

- GitHub Actions 工作流：[`/.github/workflows/roblox_rank_sync.yml`](./.github/workflows/roblox_rank_sync.yml)
- Cloudflare Worker：[`/worker`](./worker)
- 主维护手册：[`/docs/maintenance-context.zh-CN.md`](./docs/maintenance-context.zh-CN.md)
- 外部平台接入手册：[`/docs/external-platform-setup.zh-CN.md`](./docs/external-platform-setup.zh-CN.md)
- Worker 说明：[`/worker/README.md`](./worker/README.md)

## 推荐阅读顺序

1. 先读 [`docs/maintenance-context.zh-CN.md`](./docs/maintenance-context.zh-CN.md)，理解项目整体运作方式。
2. 再读 [`docs/external-platform-setup.zh-CN.md`](./docs/external-platform-setup.zh-CN.md)，按步骤接入 GitHub / Cloudflare / 飞书。
3. 最后根据需要查看 [`worker/README.md`](./worker/README.md) 和具体代码模块。
