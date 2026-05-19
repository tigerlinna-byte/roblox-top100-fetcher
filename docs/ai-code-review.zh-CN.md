# AI 自动代码审核配置说明

本文说明 GitHub Pull Request 阶段的 AI 自动代码审核机制。

## 1. 触发方式

工作流文件：

- [`.github/workflows/ai_code_review.yml`](../.github/workflows/ai_code_review.yml)

触发场景：

- PR 创建
- PR 新增提交
- PR 重新打开
- PR 从 Draft 切换为可审核状态
- GitHub Actions 页面手动触发，并传入 `pr_number`

## 2. 安全边界

该工作流使用 `pull_request_target`，但只 checkout 默认分支中的可信审核脚本，不 checkout PR 头部代码。

审核输入来自 GitHub API 读取到的 PR diff、PR 元数据、变更文件摘要和项目规范文档。这样可以在 fork PR 中使用仓库 Secret，同时避免直接执行未受信任分支里的脚本。

## 3. 必需配置

进入 GitHub 仓库：

`Settings -> Secrets and variables -> Actions`

新增 Secret：

- `OPENAI_API_KEY`：OpenAI API Key，用于调用 Responses API 生成审核意见。

## 4. 可选配置

可以在 GitHub Actions Variables 中配置：

- `OPENAI_REVIEW_MODEL`：审核模型，默认 `gpt-5.4-mini`。
- `AI_REVIEW_MAX_DIFF_CHARS`：传给模型的 diff 最大字符数，默认 `120000`。
- `AI_REVIEW_MAX_CONTEXT_CHARS`：传给模型的项目规则上下文最大字符数，默认 `24000`。
- `AI_REVIEW_MAX_OUTPUT_TOKENS`：模型最大输出 token 数，默认 `4000`。

如果 PR diff 超过字符上限，脚本会保留首尾内容并截断中间部分。超大 PR 的审核结果只能作为辅助判断，不能视为完整覆盖。

## 5. 审核规则

审核脚本会读取：

- [`AGENTS.md`](../AGENTS.md)
- [`docs/maintenance-context.zh-CN.md`](./maintenance-context.zh-CN.md)
- 本文档

AI 审核重点：

- 运行错误、数据错误、部署失败和安全风险
- Roblox / Python / GitHub Actions / Cloudflare Worker / 飞书链路行为
- 是否违反项目结构、职责划分、类型注解、中文注释和生产就绪规范
- 是否存在硬编码业务常量、死代码、临时方案、占位实现或伪实现

## 6. 输出方式

审核结果会写入 PR 评论。脚本会更新同一条带有隐藏标记的评论，避免每次提交重复刷屏。

评论结构固定为：

- 阻塞问题
- 建议问题
- 残余风险 / 人工确认点

没有发现阻塞问题时，评论会明确写出“未发现阻塞问题”。

## 7. 限制

AI 审核不能替代确定性检查。类型检查、单元测试、Worker 测试和必要的人工 Review 仍然需要保留。

AI 审核结果不应直接作为唯一合并门禁。更适合的用法是让它暴露风险，再由维护者判断是否需要修复或补测。
