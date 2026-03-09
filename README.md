# Roblox Top 100 Fetcher

A Python project that fetches Roblox top games once per run, writes JSON/CSV locally, and sends a Markdown-style summary to a Feishu group bot.

## Features

- One-shot run: execute once, fetch once, then exit
- Auto retry with exponential backoff for transient API failures
- Output both JSON and CSV for each run
- Send Feishu group message on success/failure
- GitHub Actions daily schedule (free-first setup)
- Feishu chat command trigger via Cloudflare Worker

## Requirements

- Python 3.10+

## Quick Start

1. Create virtual env and activate it.
2. Install dependencies:

```bash
py -m pip install -r requirements.txt
```

3. Configure `.env` (or environment variables):

```bash
copy .env.example .env
```

4. Run once:

```bash
py -m app.main
```

## Run tests

```bash
py -m unittest discover -s tests
```

## Output

By default files are written into `./data`:

- `top100_YYYY-MM-DD.json`
- `top100_YYYY-MM-DD.csv`

Each row/object includes:

- `rank`
- `place_id`
- `name`
- `creator`
- `playing`
- `visits`
- `up_votes`
- `down_votes`
- `fetched_at`

## Configuration

Environment variables (defaults shown):

- `OUTPUT_DIR=./data`
- `RETRY_MAX_ATTEMPTS=3`
- `RETRY_BACKOFF_SECONDS=2`
- `REQUEST_TIMEOUT_SECONDS=15`
- `API_LIMIT=100`
- `ROBLOX_SORT_ID=top-playing-now`
- `FEISHU_BOT_WEBHOOK=...`
- `FEISHU_APP_ID=...`
- `FEISHU_APP_SECRET=...`
- `FEISHU_TIMEZONE=Asia/Shanghai`
- `RUN_TRIGGER_SOURCE=manual`
- `RUN_TRIGGER_ACTOR=`
- `RUN_CHAT_ID=`
- `RUN_REPORT_MODE=top100_message`
- `ROBLOX_TOP_TRENDING_SORT_ID=` (optional override for `/roblox-top-day`)

## Feishu bot setup

1. Add a custom bot to your target Feishu group.
2. Use keyword verification, for example `Roblox`.
3. Copy the bot webhook URL.
4. Put `FEISHU_BOT_WEBHOOK` into local environment variables or GitHub Secrets if you want webhook fallback delivery.
5. Put `FEISHU_APP_ID` and `FEISHU_APP_SECRET` into local environment variables or GitHub Secrets for app-bot delivery back to the triggering chat.

## GitHub Actions schedule (free)

Workflow file:

- `.github/workflows/roblox_rank_sync.yml`

Default schedule is daily `09:00` Beijing time (`cron: 0 1 * * *` in UTC).

Set these repository secrets before enabling workflow:

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_WEBHOOK` (optional fallback)
- `GH_TOKEN` (required if `/roblox-top-day` should persist the spreadsheet token/sheet id for reuse)

Optional repository variables for spreadsheet reuse:

- `FEISHU_TOP_TRENDING_SPREADSHEET_TOKEN`
- `FEISHU_TOP_TRENDING_SHEET_ID`

Manual runs also support workflow inputs:

- `trigger_source`
- `trigger_actor`
- `chat_id`

They are shown in the Feishu summary so you can distinguish schedule runs from Feishu-triggered runs.

## Feishu manual trigger in group chat

This repo now includes a Cloudflare Worker in [`worker/`](./worker) that bridges Feishu group messages to GitHub Actions.

Chinese step-by-step external platform guide:

- [`docs/external-platform-setup.zh-CN.md`](./docs/external-platform-setup.zh-CN.md)

Architecture:

1. Feishu self-built app bot receives `/roblox-top100` or `/roblox-top-day`
2. Cloudflare Worker validates chat/user and dispatches GitHub Actions with a report mode
3. GitHub Actions runs `python -m app.main`
4. `/roblox-top100` sends the final leaderboard back to the triggering chat
5. `/roblox-top-day` writes Top Trending top 100 into a Feishu spreadsheet, reuses it on later runs, and sends the sheet link back to the triggering chat

### 1. Verify GitHub Actions first

Before connecting Feishu, make sure the workflow can already run from GitHub:

1. Push this repo to GitHub
2. Add repository secrets `FEISHU_APP_ID` and `FEISHU_APP_SECRET`
3. Optional fallback: add repository secret `FEISHU_BOT_WEBHOOK`
4. Open `Actions -> Roblox Rank Sync`
5. Click `Run workflow`
6. Confirm the job succeeds and the Feishu group receives a success message

### 2. Create GitHub token for the Worker

Create a fine-grained personal access token limited to this repository.

Recommended permissions:

- `Actions: Read and write`
- `Contents: Read`
- `Metadata: Read`

The Worker uses this token only to call the GitHub workflow dispatch API.

### 3. Deploy the Cloudflare Worker

Worker files:

- [`worker/src/index.js`](./worker/src/index.js)
- [`worker/wrangler.toml`](./worker/wrangler.toml)
- [`worker/.dev.vars.example`](./worker/.dev.vars.example)

Local test:

```bash
cd worker
node --test
```

Deploy steps:

1. Install Wrangler if needed:

```bash
cd worker
npm install -D wrangler
```

2. Configure secrets in Cloudflare:

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE=roblox_rank_sync.yml`
- `GH_REF=main`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`

3. Deploy:

```bash
cd worker
npx wrangler deploy
```

Routes exposed by the Worker:

- `GET /health`
- `POST /feishu/events`

### 4. Configure Feishu self-built app

In Feishu Open Platform:

1. Create a self-built app
2. Enable bot capability
3. Enable event subscription
4. Subscribe to group text message receive events
5. Set the callback URL to:

```text
https://<your-worker-domain>/feishu/events
```

6. Finish the Feishu event URL verification
7. Add the app bot to your target group

### 5. Manual trigger command

Send this exact text in the allowed Feishu group:

```text
/roblox-top100
/roblox-top-day
```

Expected behavior:

1. The Worker immediately acknowledges the request in the same group
2. GitHub Actions starts a new workflow run
3. The Python job posts the final success or failure summary back to the group

## Security defaults

- The Worker only accepts the exact command `/roblox-top100`
- The Worker also accepts the exact command `/roblox-top-day`
- `ALLOWED_CHAT_IDS` can restrict which groups may trigger the workflow
- `ALLOWED_OPEN_IDS` can restrict which users may trigger the workflow
- `FEISHU_VERIFICATION_TOKEN` is checked on incoming Feishu events

## Notes about Roblox endpoint

Roblox public game list endpoints have changed over time. This project uses:

- `GET https://apis.roblox.com/explore-api/v1/get-sort-content`
- `GET https://games.roblox.com/v1/games?universeIds=...`

with sort id `top-playing-now`.

If Roblox changes response shape again, adjust parser logic in `app/roblox_client.py`.
