# Deployment

## Requirements

- Ubuntu 22.04+ (or similar Linux with X11/Wayland for desktop tools)
- Python 3.12+
- Node.js 22+ and pnpm (for OpenClaw)
- ffmpeg (voice messages)
- Optional: Happ VPN / HTTP proxy on `127.0.0.1:10809` if Telegram is blocked

## Quick start

```bash
git clone https://github.com/YOUR_ORG/jarvis-agent.git
cd jarvis-agent

cp pds_ultimate/.env.example pds_ultimate/.env
# Edit: TG_BOT_TOKEN, TG_OWNER_ID, DEEPSEEK_API_KEY, TG_PROXY

bash scripts/install.sh    # venv + OpenClaw + configs (~5–10 min first time)
bash scripts/start.sh      # bridge :8765 + gateway :18789
```

Message your bot on Telegram.

## Docker

```bash
docker compose up -d
```

See root `docker-compose.yml` for service layout.

## Production tips

- Run `pds_ultimate/scripts/watchdog_hybrid.sh` under systemd or the included start script
- Set `gateway.controlUi.enabled: false` (default in example config) — no web UI needed for Telegram-only use
- Keep secrets in `.env` only; run `python3 scripts/render_openclaw_config.py` after env changes
- Logs: `pds_ultimate/data/{bridge,openclaw,pds_main}.log`

## Updating OpenClaw

```bash
cd vendor/openclaw && git pull && pnpm install && pnpm build
cp -a ../../openclaw-plugin/manus-bridge extensions/
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ECONNREFUSED :8765` | Start bridge: `python -m bridge.ws_server` from repo with PYTHONPATH set |
| Telegram network errors | Set `TG_PROXY=http://127.0.0.1:10809` in `.env`, re-render config |
| OpenClaw UI build loop | Ensure `controlUi.enabled: false` in config |
| Telethon loop errors | MCP uses dedicated asyncio thread (`bridge/async_loop.py`) |
