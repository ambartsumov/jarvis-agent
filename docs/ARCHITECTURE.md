# Architecture

Jarvis Agent is a **hybrid personal AI stack**: OpenClaw handles channels and
sessions; OpenManus is the reasoning engine; PDS provides memory and integrations.

## Component map

```
Telegram / Voice
       │
       ▼
┌──────────────────┐     WebSocket      ┌─────────────────────┐
│  OpenClaw        │ ◄──────────────────► │  OpenManus bridge   │
│  gateway :18789  │   manus-bridge plugin│  ws_server :8765    │
└──────────────────┘                      └──────────┬──────────┘
                                                       │
                       ┌───────────────────────────────┼────────────────┐
                       ▼                               ▼                ▼
                 DeepSeek LLM                    MCP pds-*         bash/desktop
                       │                               │                │
                       └───────────────────────────────┴────────────────┘
                                                       │
                                                       ▼
                                              pds_ultimate (SQLite,
                                              Telethon, Green-API)
```

## Repository layout

| Path | Role |
|------|------|
| `pds_ultimate/` | Memory, DB, integrations, legacy bot |
| `pds_ultimate/OpenManus-main/` | Vendored OpenManus + `bridge/` glue |
| `openclaw-plugin/manus-bridge/` | OpenClaw plugin (TypeScript) |
| `vendor/openclaw/` | Cloned OpenClaw (not in git) |
| `config/` | Example configs (no secrets) |
| `scripts/` | Install, start, verify |

## Message flow

1. User sends Telegram message → OpenClaw telegram plugin
2. `before_agent_reply` hook in manus-bridge intercepts
3. Plugin sends `run` over WebSocket to `bridge/ws_server.py`
4. `StreamingManus` runs Think–Act–Observe with tools + MCP
5. Events stream back (progress bar); final answer sent via Bot API

## MCP servers

| Server | Tools | Backend |
|--------|-------|---------|
| `pds-memory` | remember, recall, lessons | SQLite via `core/memory/` |
| `pds-telegram` | dialogs, read, send | Telethon userbot |
| `pds-whatsapp` | status, read, send | Green-API |

## Dual modes

| Mode | Entry | Use case |
|------|-------|----------|
| **Hybrid** (default) | `scripts/start.sh` | Production: OpenClaw + Manus |
| Legacy | `OPENCLAW_TELEGRAM=0 python -m pds_ultimate.main` | Aiogram bot only |

Do not run both Telegram bots simultaneously.
