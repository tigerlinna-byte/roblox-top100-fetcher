# 外部平台配置实操手册

这份手册对应当前仓库的实现，目标是完成两件事：

1. GitHub Actions 每天自动抓取 Roblox Top 100
2. 飞书群内发送 `/roblox-top100` 可手动触发一次抓取

整套链路如下：

1. 飞书群消息进入自建应用机器人
2. Cloudflare Worker 校验消息并调用 GitHub Actions
3. GitHub Actions 执行 `python -m app.main`
4. Python 程序通过飞书自定义机器人 webhook 回传结果

## 准备信息

开始前先准备好这些值：

- GitHub 仓库名
- GitHub 用户名或组织名
- 飞书群自定义机器人 `webhook`
- 飞书开放平台自建应用的 `App ID`
- 飞书开放平台自建应用的 `App Secret`
- 飞书事件订阅里的 `Verification Token`

## 第 1 步：配置 GitHub Actions

### 1.1 推送代码

把当前项目推到 GitHub 仓库，默认分支建议使用 `main`。

仓库里必须包含：

- `.github/workflows/roblox_rank_sync.yml`
- `worker/`

### 1.2 配置飞书结果通知 Secret

进入 GitHub 仓库页面：

`Settings -> Secrets and variables -> Actions -> New repository secret`

新增：

- `FEISHU_BOT_WEBHOOK`

值填写飞书群自定义机器人的 webhook。

### 1.3 先验证 GitHub 可以独立运行

进入：

`Actions -> Roblox Rank Sync -> Run workflow`

执行一次手动任务。成功标准：

- 工作流状态是绿色
- 飞书群收到排行榜成功消息

如果这一步不通，先不要继续配置 Worker 和飞书事件。

### 1.4 创建给 Worker 使用的 GitHub Token

进入：

`GitHub -> Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens`

创建 token，限制到当前仓库，权限最少给：

- `Actions: Read and write`
- `Contents: Read`
- `Metadata: Read`

保存这串 token，后面 Cloudflare 里会用到。

## 第 2 步：配置 Cloudflare Worker

### 2.1 安装和登录 Wrangler

在仓库根目录打开终端，执行：

```powershell
cd worker
npm install -D wrangler
npx wrangler login
```

### 2.2 创建 Worker

登录 Cloudflare 后，进入 `Workers & Pages`，创建一个 Worker。

名称建议：

- `roblox-top100-feishu-trigger`

当前仓库中的配置文件是：

- `worker/wrangler.toml`

默认可直接使用。

### 2.3 写入 Worker secrets

你有两种方式：

方式 A：手动一条条执行

```powershell
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
```

方式 B：使用仓库自带脚本批量提示输入

```powershell
cd worker
powershell -ExecutionPolicy Bypass -File .\set-secrets.ps1
```

各 secret 填值如下：

- `GH_TOKEN`：GitHub fine-grained token
- `GH_OWNER`：GitHub 用户名或组织名
- `GH_REPO`：仓库名
- `GH_WORKFLOW_FILE`：`roblox_rank_sync.yml`
- `GH_REF`：`main`
- `FEISHU_APP_ID`：飞书应用 App ID
- `FEISHU_APP_SECRET`：飞书应用 App Secret
- `FEISHU_VERIFICATION_TOKEN`：飞书事件订阅 Verification Token
- `ALLOWED_CHAT_IDS`：允许触发的群 ID，多个用英文逗号分隔
- `ALLOWED_OPEN_IDS`：允许触发的用户 open_id，多个用英文逗号分隔；如暂不限制可留空

### 2.4 部署 Worker

```powershell
cd worker
npx wrangler deploy
```

部署成功后记下域名，例如：

`https://roblox-top100-feishu-trigger.<subdomain>.workers.dev`

### 2.5 健康检查

浏览器访问：

`https://你的worker域名/health`

应返回 JSON，包含：

```json
{"ok":true,"service":"feishu-gh-dispatch"}
```

## 第 3 步：配置飞书开放平台

### 3.1 创建自建应用
 
打开：

https://open.feishu.cn/

创建一个“自建应用”。

### 3.2 开启机器人能力

在应用能力里启用机器人，使其可以被拉入群聊。

### 3.3 开启事件订阅

在事件订阅中配置回调地址：

`https://你的worker域名/feishu/events`

同时记录：

- `Verification Token`

这个值必须与 Worker secret `FEISHU_VERIFICATION_TOKEN` 一致。

### 3.4 订阅群文本消息事件

订阅“接收消息”相关事件，确保群内文本消息会投递到 Worker。

### 3.5 开启发消息权限

为应用开通给群会话发消息的权限，目的只有一个：收到命令后回一条“已提交任务”。

### 3.6 发布应用版本

如果未发布，事件和权限常常不会真正生效。

### 3.7 将应用机器人加入目标飞书群

加入后，你的群里会有两类机器人：

- 自定义机器人：负责接收最终排行榜结果
- 自建应用机器人：负责响应 `/roblox-top100`

## 第 4 步：拿到群 ID 和用户 open_id

第一次打通链路时，建议先把这两个限制留空：

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`

重新部署 Worker 后，在目标群发送：

```text
/roblox-top100
```

如果没有成功触发，去 Cloudflare Worker 日志里查看请求体，提取：

- `chat_id`
- `open_id`

然后把这些值重新写回 Worker secrets，再部署一次。

## 第 5 步：完整联调

在飞书群发送：

```text
/roblox-top100
```

正确结果应按顺序出现：

1. 群里立即收到“已提交 Roblox 排行榜抓取任务，稍后会回传结果。”
2. GitHub Actions 出现新的 workflow run
3. 运行结束后，飞书群收到最终排行榜结果

## 排障顺序

如果失败，按这个顺序排查：

1. GitHub 手动 `Run workflow` 是否成功
2. Worker `/health` 是否正常
3. 飞书事件订阅 URL 校验是否成功
4. Worker secrets 是否完整
5. GitHub token 是否有 `Actions: Read and write`
6. 飞书应用是否已发布且机器人已入群
7. `ALLOWED_CHAT_IDS` / `ALLOWED_OPEN_IDS` 是否误填