# Configuration

All secrets live in **`pds_ultimate/.env`**. Copy from `.env.example`.

## Required variables

| Variable | Description |
|----------|-------------|
| `TG_BOT_TOKEN` | Bot token from @BotFather |
| `TG_OWNER_ID` | Your numeric Telegram user ID |
| `DEEPSEEK_API_KEY` | DeepSeek API key |

## Proxy (regions with blocked Telegram)

| Variable | Example |
|----------|---------|
| `TG_PROXY` | `http://127.0.0.1:10809` |

Happ VPN / V2Ray typically exposes HTTP on **10809** and SOCKS5 on **10808**.

After changing proxy:

```bash
python3 scripts/render_openclaw_config.py
# restart gateway
```

## Optional integrations

| Variable | Service |
|----------|---------|
| `TG_API_ID`, `TG_API_HASH` | Telethon userbot (read/send as you) |
| `WA_GREEN_API_*` | WhatsApp via Green-API |
| `GMAIL_*`, Google OAuth | Email + calendar tools |
| `SUDO_PASSWORD` | Privileged desktop commands |

## Generated files (do not commit)

| File | Generator |
|------|-----------|
| `pds_ultimate/config/openclaw.hybrid.json` | `scripts/render_openclaw_config.py` |
| `OpenManus-main/config/config.toml` | `pds_ultimate/scripts/gen_openmanus_config.py` |
| `OpenManus-main/config/mcp.json` | same |

## OpenClaw template

Edit `config/openclaw.hybrid.example.json` for structural changes, then re-render.

Key settings:

- `plugins.entries.manus-bridge` — WebSocket URL, intercept, progress
- `channels.telegram.proxy` — Bot API proxy
- `messages.queue.mode` — `followup` for message queue
- `gateway.controlUi.enabled` — `false` for Telegram-only

## Environment overrides

| Variable | Default |
|----------|---------|
| `OPENCLAW_DIR` | `./vendor/openclaw` |
| `MANUS_BRIDGE_WS` | `ws://127.0.0.1:8765/manus` |
| `OPENCLAW_GATEWAY_PORT` | `18789` |
