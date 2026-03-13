# Feishu Trigger Worker

This Cloudflare Worker receives a Feishu bot event, validates the sender, triggers the GitHub Actions workflow, and posts an acknowledgement back to the same group chat.
It also supports Cloudflare Cron Triggers for both the daily Top100 trending sheet and the Shoot Or Shot project metrics sheet.

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

`worker/wrangler.toml` currently configures two daily cron triggers:

- Top100 trending sheet: UTC `01:00` (`0 1 * * *`)
- Shoot Or Shot project metrics: UTC `19:11` / Beijing `03:11` (`11 19 * * *`)

Top100 scheduled dispatch still requires `SCHEDULE_CHAT_IDS` and sends the final result back to those chats.
Shoot Or Shot scheduled dispatch does not pass `chat_id`; final Feishu delivery falls back to the existing `FEISHU_BOT_WEBHOOK`.

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
