"""Google OAuth — Gmail + Calendar (shared token)."""

from __future__ import annotations

from pathlib import Path

from app.integrations.env_config import GMAIL_CREDENTIALS, GMAIL_TOKEN

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def get_google_credentials(*, interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None, "pip install google-auth google-auth-oauthlib google-api-python-client"

    creds = None
    token_file = GMAIL_TOKEN
    creds_file = GMAIL_CREDENTIALS

    try:
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), GOOGLE_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
    except Exception as exc:
        return None, f"token error: {exc}"

    if creds and creds.valid:
        return creds, ""

    if not creds_file.exists():
        return None, f"OAuth credentials missing: {creds_file}"
    return None, (
        f"Run OAuth once: cd pds_ultimate && python3 -m integrations.gmail_auth "
        f"(saves token → {token_file})"
    )


def build_google_service(api: str, version: str):
    creds, reason = get_google_credentials()
    if not creds:
        return None, reason
    try:
        from googleapiclient.discovery import build

        return build(api, version, credentials=creds, cache_discovery=False), ""
    except Exception as exc:
        return None, str(exc)
