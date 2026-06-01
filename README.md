<p align="center">
  <h1 align="center">🤖 Jarvis Agent</h1>
  <p align="center">
    <strong>Self-hosted, open-source personal AI assistant — Telegram-first, offline voice, desktop control, persistent memory.</strong>
  </p>
  <p align="center">
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License"></a>
    <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+"></a>
    <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/node-22+-339933?logo=nodedotjs&logoColor=white" alt="Node 22+"></a>
    <a href="docs/ARCHITECTURE.md"><img src="https://img.shields.io/badge/docs-architecture-0891b2" alt="Architecture"></a>
    <a href="https://github.com/ambartsumov/jarvis-agent/actions"><img src="https://img.shields.io/github/actions/workflow/status/ambartsumov/jarvis-agent/ci.yml?label=CI" alt="CI"></a>
    <img src="https://img.shields.io/badge/voice-Vosk%20offline-8A2BE2" alt="Vosk offline STT">
    <img src="https://img.shields.io/badge/Telegram-Bot%20%2B%20Userbot-26A5E4?logo=telegram" alt="Telegram">
  </p>
</p>

---

> **Jarvis Agent** glues together three world-class open-source projects — **[OpenClaw](#-built-on-the-shoulders-of-giants)**, **[OpenManus](#-built-on-the-shoulders-of-giants)**, and **[Vosk](#-built-on-the-shoulders-of-giants)** — into a single, production-ready personal assistant stack you can run on your own hardware in minutes.

## ✨ What can it do?

| Capability | Details |
|---|---|
| 🤖 **Autonomous reasoning** | OpenManus Think–Act–Observe loop with 60+ built-in tools |
| 💬 **Telegram-first UI** | Bot + Telethon userbot — no web UI needed |
| 🗣️ **Offline voice (Vosk)** | Russian / English STT, SRT subtitles, no GPU required |
| 🖥️ **Desktop control** | Screenshots, window management, hotkeys, notifications (Linux) |
| 🧠 **Persistent memory** | MemGPT-inspired hierarchy: working → short-term → long-term SQLite |
| 📱 **WhatsApp** | Green-API integration |
| 📅 **Google Calendar + Gmail** | Full OAuth read/write |
| 📦 **Logistics & Finance** | Order lifecycle, profit calculator, multi-currency |
| 🌐 **Proxy/VPN friendly** | All network calls auto-detect proxy; designed for restricted regions |
| 🔒 **Guardrails** | Prompt-injection detection, rate limiting, PII redaction |

## 🏗️ Architecture (30 seconds)

```
Telegram ──▶ OpenClaw :18789 ──▶ manus-bridge ──▶ OpenManus WS :8765 ──▶ DeepSeek + tools + MCP
                                                          │
                                                 pds_ultimate (SQLite memory + integrations)
                                                          │
                                                  Vosk STT (offline, no GPU)
```

Full component map and message flow → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 🚀 Quick start

### 1. Clone & configure

```bash
git clone https://github.com/ambartsumov/jarvis-agent.git
cd jarvis-agent

cp pds_ultimate/.env.example pds_ultimate/.env
```

Edit `pds_ultimate/.env` — required keys:

```env
TG_BOT_TOKEN=          # from @BotFather
TG_OWNER_ID=           # from @userinfobot
DEEPSEEK_API_KEY=      # https://platform.deepseek.com

# Optional — offline voice (Vosk)
VOSK_MODEL_PATH=vosk/vosk-model-small-ru-0.22
STT_BACKEND=vosk       # or grok (needs GROK_API_KEY)

# If Telegram is blocked in your region
TG_PROXY=http://127.0.0.1:10809
```

### 2. Install

```bash
bash scripts/install.sh
```

Installs Python venv, generates configs, clones & builds OpenClaw into `vendor/openclaw`.
Skip OpenClaw: `SKIP_OPENCLAW=1 bash scripts/install.sh`

Download a [Vosk model](vosk/README.md#download-a-vosk-model) and unzip it to `vosk/`.

### 3. Run

```bash
bash scripts/start.sh
```

Write to your bot on Telegram. Logs → `pds_ultimate/data/`.

## 📁 Repository layout

```
jarvis-agent/
├── pds_ultimate/              # Memory, DB, integrations, bot handlers
│   └── OpenManus-main/        # Vendored OpenManus + ws_server bridge
├── openclaw-plugin/
│   └── manus-bridge/          # OpenClaw plugin (TypeScript) — Telegram ↔ WS
├── vosk/                      # Offline STT — transcribe.py, sharetape.py
├── config/                    # Example configs — no secrets committed
├── docs/                      # Architecture, deployment, configuration guides
├── scripts/                   # install.sh, start.sh, verify_imports.py
└── vendor/openclaw/           # Created by install (gitignored)
```

## 📚 Documentation

| Document | Contents |
|----------|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component diagram, message flow, MCP |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Production, Docker, systemd, troubleshooting |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | All environment variables |
| [vosk/README.md](vosk/README.md) | Offline STT setup |
| [CONTRIBUTING.md](CONTRIBUTING.md) | PR guidelines, code style |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |

## 🧪 Verify installation

```bash
python3 scripts/verify_imports.py
python3 scripts/render_openclaw_config.py
```

## 🐳 Docker

```bash
docker compose up --build
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full wiring details.

## 🔧 Key environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TG_BOT_TOKEN` | ✅ | Telegram bot token (@BotFather) |
| `TG_OWNER_ID` | ✅ | Your Telegram user ID (@userinfobot) |
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API key |
| `VOSK_MODEL_PATH` | — | Path to unzipped Vosk model |
| `STT_BACKEND` | — | `vosk` (offline) or `grok` (cloud) |
| `GROK_API_KEY` | — | xAI Grok key (only when `STT_BACKEND=grok`) |
| `TG_PROXY` | — | HTTP proxy for Telegram API |

Full reference → [docs/CONFIGURATION.md](docs/CONFIGURATION.md)

## 🏆 Built on the shoulders of giants

This project would not exist without the incredible work of these teams and authors:

---

### [OpenClaw](https://github.com/openclaw/openclaw)

> **Multi-channel AI gateway** — Telegram sessions, media handling, plugin system.

OpenClaw handles all incoming Telegram traffic. The `openclaw-plugin/manus-bridge/` TypeScript plugin in this repo intercepts messages via OpenClaw's `before_agent_reply` hook and forwards them to the OpenManus reasoning engine over WebSocket.

*Thank you to the OpenClaw team for building a rock-solid, extensible gateway that makes plugging in any AI backend dead simple.*

- Repository: https://github.com/openclaw/openclaw
- License: MIT

---

### [OpenManus](https://github.com/FoundationAgents/OpenManus)

> **Open-source autonomous agent framework** by FoundationAgents — Think, Act, Observe.

OpenManus is the reasoning brain (vendored as `pds_ultimate/OpenManus-main/`). It provides tool calling, MCP support, multi-agent orchestration, and streaming. Jarvis adds persistent memory, Telegram/WhatsApp integrations, finance/logistics modules, and scheduling on top.

*Thank you to the FoundationAgents team and all OpenManus contributors for creating a world-class, truly open agentic framework.*

- Repository: https://github.com/FoundationAgents/OpenManus
- License: MIT

---

### [Vosk](https://alphacephei.com/vosk/) + [KaldiASR](https://kaldi-asr.org/)

> **Offline speech recognition** — runs on CPU, no GPU, no internet required.

Vosk powers the offline STT layer in `vosk/`. The standalone CLI (`vosk/transcribe.py`) is based on [Sharetape-Speech-To-Text](https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text) by **Clint Kristopher Morris**. Vosk itself is built on Kaldi and maintained by [Alpha Cephei](https://alphacephei.com/).

*Thank you to Clint Kristopher Morris for the clean Vosk wrapper, and to the Alpha Cephei team for making production-grade offline STT available to everyone.*

- Vosk: https://alphacephei.com/vosk/ (Apache 2.0)
- Kaldi: https://kaldi-asr.org/ (Apache 2.0)
- Sharetape: https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text (MIT)

---

See [THIRD_PARTY.md](THIRD_PARTY.md) for the full dependency list.

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs are especially welcome for:

- New OpenClaw plugins (other channels)
- Additional MCP tool servers
- Vosk model integrations for more languages
- Test coverage improvements

## 📄 License

[MIT](LICENSE) © 2026 Jarvis Agent Contributors

---

<p align="center">
  <sub>⭐ Star the repo if Jarvis helps you — it means a lot and helps others find it!</sub>
</p>
