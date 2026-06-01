# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| main    | yes       |

## Reporting a vulnerability

Please **do not** open public issues for security-sensitive reports.

1. Email the maintainer privately (GitHub profile contact or repository owner).
2. Include steps to reproduce, impact assessment, and suggested fix if any.
3. Allow up to 7 days for an initial response.

## Secrets handling

- Never commit `.env`, `*.session`, OAuth tokens, or API keys.
- Use `pds_ultimate/.env.example` as a template only.
- Rotate Telegram bot tokens and API keys if accidentally exposed.

## Operational security

- Jarvis can execute shell commands and control the desktop when enabled.
- Restrict `TG_OWNER_ID` and OpenClaw `ownerAllowFrom` to trusted accounts only.
- Run the gateway on `127.0.0.1` unless you understand exposure risks.
