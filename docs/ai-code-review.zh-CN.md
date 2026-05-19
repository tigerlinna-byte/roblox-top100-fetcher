# AI 自动代码审核配置说明

本文说明 GitHub push 后的 AI 自动代码审核机制。

## 1. 触发方式

工作流文件：

- [`.github/workflows/ai_code_review.yml`](../.github/workflows/ai_code_review.yml)

触发场景：

- 向 `main` 分支 push 后自动触发
- GitHub Actions 页面手动触发，并传入 `base_sha` 与 `head_sha`

当前项目不再把 AI 审核绑定到 Pull Request。日常流程是直接提交并推送到目标分支，由 push 后的 Actions 审核输出风险提示。

## 2. 安全边界

该工作流运行在已推送的仓库代码上，使用 GitHub Compare API 读取 `base_sha...head_sha` 的统一 diff 和变更文件列表。

审核脚本不会执行被审核代码，只读取 diff、提交摘要和仓库内规范文档，然后调用 OpenAI Responses API 生成审核意见。

## 3. 必需配置

进入 GitHub 仓库：

`Settings -> Secrets and variables -> Actions`

新增或确认 Secret：

- `OPENAI_API_KEY`：OpenAI API Key，用于调用 Responses API 生成审核意见。

如果要把审核结果发送到飞书 Test 对话窗，还需要：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

新增或确认 Variable：

- `AI_REVIEW_FEISHU_CHAT_ID`：AI 审核结果发送到的飞书 Test 对话窗 `chat_id`。

如果确实想把 `AI_REVIEW_FEISHU_CHAT_ID` 当作 Secret 管理，workflow 也支持同名 Secret。

## 4. 可选配置

可以在 GitHub Actions Variables 中配置：

- `OPENAI_REVIEW_MODEL`：审核模型，默认 `gpt-5.4-mini`。
- `AI_REVIEW_MAX_DIFF_CHARS`：传给模型的 diff 最大字符数，默认 `120000`。
- `AI_REVIEW_MAX_CONTEXT_CHARS`：传给模型的项目规则上下文最大字符数，默认 `24000`。
- `AI_REVIEW_MAX_OUTPUT_TOKENS`：模型最大输出 token 数，默认 `4000`。

如果 diff 超过字符上限，脚本会保留首尾内容并截断中间部分。超大提交的审核结果只能作为辅助判断，不能视为完整覆盖。

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

审核结果会同时输出到：

- GitHub Actions Summary
- `AI_REVIEW_FEISHU_CHAT_ID` 指定的飞书 Test 对话窗

飞书通知失败不会让 workflow 失败；脚本会在 Actions 日志中打印 warning。AI 审核发现风险也不会阻断提交，只作为自动风险提示。

审核结果结构固定为：

- 阻塞问题
- 建议问题
- 残余风险 / 人工确认点

没有发现阻塞问题时，结果会明确写出“未发现阻塞问题”。

## 7. 限制

AI 审核不能替代确定性检查。类型检查、单元测试、Worker 测试和必要的人工判断仍然需要保留。

AI 审核结果不作为合并门禁。更适合的用法是让它在提交后暴露风险，再由维护者判断是否需要修复或补测。
