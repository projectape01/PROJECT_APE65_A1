# LINE Bot Edge Function

This Supabase Edge Function is intended to replace the Raspberry Pi `/line/webhook`
endpoint so LINE chat commands still work when the Pi is powered off.

## Required secrets

Set these on Supabase before deploying:

```bash
supabase secrets set LINE_CHANNEL_ACCESS_TOKEN="..."
supabase secrets set LINE_CHANNEL_SECRET="..."
supabase secrets set PROJECT_SUPABASE_SERVICE_ROLE_KEY="..."
supabase secrets set PROJECT_SUPABASE_URL="https://ptxfbxwufbrivfrcplku.supabase.co"
```

`PROJECT_SUPABASE_SERVICE_ROLE_KEY` is recommended because the bot reads production data
server-side. Do not expose it in frontend code.

## Deploy

```bash
supabase functions deploy line-bot --no-verify-jwt
```

Then set the LINE Messaging API webhook URL to:

```text
https://<project-ref>.supabase.co/functions/v1/line-bot
```

## Supported commands

- `status`
- `summary`
- `now`
- `part <id>`

The Pi can be offline and these commands will still answer from Supabase data.
