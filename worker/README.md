# Feishu Trigger Worker

This Cloudflare Worker receives a Feishu bot event, validates the sender, triggers the GitHub Actions workflow, and posts an acknowledgement back to the same group chat.
It also supports Cloudflare Cron Triggers for scheduled Top Trending sheet dispatches.

## Routes

- `GET /health`
- `POST /feishu/events`

## Accepted command

- `/roblox-top100`

## Required secrets

- `GH_TOKEN`
- `GH_OWNER`
- `GH_REPO`
- `GH_WORKFLOW_FILE`
- `GH_REF`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`

## Optional secrets

- `ALLOWED_CHAT_IDS`
- `ALLOWED_OPEN_IDS`
- `COMMAND_TEXT`
- `TOP_DAY_COMMAND_TEXT`
- `SCHEDULE_CHAT_IDS`

## Scheduled trigger

`worker/wrangler.toml` currently configures a daily cron trigger at Beijing `10:14` (`14 2 * * *` in UTC).

Set `SCHEDULE_CHAT_IDS` to one or more comma-separated Feishu `chat_id` values if the cron trigger should dispatch the Top Trending sheet workflow automatically.

## Local test

```bash
cd worker
node --test
```

## Deploy

1. Install Wrangler if needed: `npm install -D wrangler`
2. Copy `.dev.vars.example` to `.dev.vars` for local dev
3. Set production secrets with `wrangler secret put ...` or run `powershell -ExecutionPolicy Bypass -File .\set-secrets.ps1`
4. Deploy with `npx wrangler deploy`
