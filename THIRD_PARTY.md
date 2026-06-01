# Third-Party Notices

Jarvis Agent integrates and builds upon the following open-source projects.
We are grateful to all upstream authors and contributors.

---

## OpenClaw

- **Repository:** https://github.com/openclaw/openclaw
- **License:** MIT
- **Location:** installed to `vendor/openclaw/` via `scripts/install_openclaw.sh`
- **Usage:** Multi-channel AI gateway (Telegram sessions, media, plugin system).
  The `openclaw-plugin/manus-bridge/` TypeScript plugin in this repo hooks into
  OpenClaw's `before_agent_reply` event to forward messages to the OpenManus
  WebSocket reasoning engine.

---

## OpenManus

- **Repository:** https://github.com/FoundationAgents/OpenManus
- **License:** MIT
- **Location in tree:** `pds_ultimate/OpenManus-main/`
- **Usage:** Python autonomous agent runtime (Think–Act–Observe loop), tool registry,
  MCP host, multi-agent orchestration, streaming output.

---

## Vosk Speech Recognition

- **Website:** https://alphacephei.com/vosk/
- **Repository:** https://github.com/alphacep/vosk-api
- **License:** Apache 2.0
- **Location in tree:** `vosk/` (STT wrapper), `pds_ultimate/core/speech_to_text.py` (offline fallback)
- **Usage:** Offline, CPU-only speech-to-text for Russian and English voice messages.
  Models are downloaded separately and are not included in this repository.

## Kaldi ASR

- **Website:** https://kaldi-asr.org/
- **License:** Apache 2.0
- **Usage:** Underlying ASR engine used by Vosk.

## Sharetape-Speech-To-Text

- **Repository:** https://github.com/clint-kristopher-morris/Sharetape-Speech-To-Text
- **Author:** Clint Kristopher Morris
- **License:** MIT
- **Location in tree:** `vosk/transcribe.py`, `vosk/sharetape.py`
- **Usage:** Vosk CLI wrapper for transcribing video/audio to text, word timestamps,
  and SRT captions. Modified to support `--model` argument.

---

## PDS-Ultimate core

- **Origin:** Personal Data System — business assistant modules
- **License:** MIT (this repository)
- **Location:** `pds_ultimate/` (excluding vendored OpenManus)
- **Components:** Memory hierarchy, scheduler, Telethon userbot, WhatsApp integration,
  Gmail, Google Calendar, finance/logistics modules, guardrails, persona adaptation.

---

## Other runtime dependencies

See `pds_ultimate/requirements.txt` and `openclaw-plugin/manus-bridge/package.json`
for the full list of runtime packages including:

- **aiogram** — Telegram Bot framework (MIT)
- **telethon** — Telegram userbot library (MIT)
- **httpx** — Async HTTP client (BSD)
- **SQLAlchemy** — ORM (MIT)
- **APScheduler** — Job scheduler (MIT)
- **DeepSeek Python client** — LLM API (MIT)
- **Playwright** — Browser automation (Apache 2.0)

