---
name: roblox-top100-context
description: Restore project context for roblox-top100-fetcher before handling new requirements. Use when a task asks for new features, bug fixes, behavior changes, workflow changes, deployment/configuration changes, Feishu/GitHub/Cloudflare integration changes, Roblox ranking or creator analytics changes, or any request that requires understanding this repository's current architecture before planning.
---

# Roblox Top100 Context

## 目标

在处理 `roblox-top100-fetcher` 的新需求前，先恢复项目上下文，按最小必要原则读取文档，并输出影响面判断。该 skill 只定义上下文恢复流程；项目事实以仓库内 `docs/` 文档和当前代码为准。

## 适用边界

使用该 skill 时，必须遵守项目根目录 `AGENTS.md`。如果用户尚未明确回复“确认执行”，不得修改文件、输出可直接执行的命令或进入编码阶段。

## 工作流

### 1. 新需求分类

先判断用户请求属于哪些链路。一个需求可以命中多个分类：

- 榜单摘要：`top100_message`
- Top Trending 多 Sheet：`top_trending_sheet`
- 项目日报：`roblox_project_daily_metrics`
- Worker / Cron / GitHub Actions 触发桥接
- 飞书、Cloudflare、GitHub 外部平台配置
- Roblox Explore 接口数据完整性、漏游戏、排序异常或榜单返回不足

如果分类不明确，先说明判断依据和假设。需求、数据或行为存在关键不确定性时，先向用户确认，不得基于猜测进入实现。

### 2. 按需读取文档

从仓库根目录读取文档，遵循“最小必要、按需补读”：

- 默认先读 `docs/maintenance-context.zh-CN.md`，用于建立项目整体上下文。
- 只有需求涉及外部平台接入、部署、密钥、飞书应用、Cloudflare Worker、GitHub Actions 或三端联调时，才补读 `docs/external-platform-setup.zh-CN.md`。
- 只有需求涉及 Roblox Explore 榜单漏游戏、排序异常、接口返回条数不足、榜单完整性或替代 sortId 时，才补读 `docs/roblox-explore-api-data-gap-report.zh-CN.md`。

不得默认一次性读取所有文档。读取后如果文档与当前代码不一致，先指出差异，再以当前代码实际行为作为最终判断依据。

### 3. 输出影响面判断

在给出实现方案前，必须说明本次需求是否影响以下范围：

- Cloudflare Worker
- GitHub Actions
- Python 主流程
- 配置入口
- 飞书消息或表格
- GitHub Variables / Secrets
- 本地数据产物或 artifacts
- 测试
- 维护文档

对每一项给出“影响 / 不影响 / 待确认”的明确判断。影响项必须说明原因和预计改动位置。

## 输出格式

面向用户输出方案时，至少包含：

1. 需求分类
2. 已读取文档
3. 关键上下文结论
4. 影响面判断
5. 不确定点或需要用户确认的问题
6. 下一步实现方案

只有在用户明确回复“确认执行”后，才进入文件修改或编码阶段。
