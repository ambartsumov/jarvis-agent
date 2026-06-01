## Topics

Add these topics in GitHub repo settings for discoverability:

`ai-agent` `telegram-bot` `openmanus` `openclaw` `personal-assistant` `deepseek` `mcp` `linux` `python` `typescript` `self-hosted` `jarvis`

## Repository description

```
🤖 Jarvis Agent — personal AI for Telegram: OpenManus brain + OpenClaw gateway + desktop control, memory, WhatsApp/TG MCP
```

## Social preview

Use a screenshot of Telegram chat with the agent or architecture diagram from docs/ARCHITECTURE.md.

## Push (if not done automatically)

```bash
gh auth login -h github.com
# or with proxy:
HTTPS_PROXY=http://127.0.0.1:10809 gh auth login -h github.com

cd /home/slavik/agent
gh repo create qwert2009/jarvis-agent --public --source=. --remote=origin --push
# or:
git remote add origin git@github.com:qwert2009/jarvis-agent.git
git push -u origin main
```
