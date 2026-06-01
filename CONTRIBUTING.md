# Contributing to Jarvis Agent

Thank you for your interest in contributing.

## Development setup

```bash
git clone https://github.com/YOUR_ORG/jarvis-agent.git
cd jarvis-agent
bash scripts/install.sh
```

## Before submitting a PR

1. Run import smoke test: `python3 scripts/verify_imports.py`
2. Do not commit secrets (`.env`, sessions, tokens)
3. Keep changes focused — one feature or fix per PR
4. Update docs if you change architecture or config

## Code style

- **Python:** match existing modules in `pds_ultimate/` and `OpenManus-main/bridge/`
- **TypeScript:** match `openclaw-plugin/manus-bridge/` conventions
- Prefer minimal diffs; avoid drive-by refactors

## Architecture docs

See `docs/ARCHITECTURE.md` before large changes.

## Questions

Open a GitHub Discussion or Issue with the `question` label.
