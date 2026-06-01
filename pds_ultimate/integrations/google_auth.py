"""Unified Google OAuth — Gmail + Calendar from one token."""

from __future__ import annotations

from pathlib import Path

from pds_ultimate.config import config, logger

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def _credentials_path() -> Path:
    return config.gmail.credentials_file


def _token_path() -> Path:
    return config.gmail.token_file


def get_google_credentials(*, interactive: bool = False):
    """Load or refresh OAuth credentials. Returns (creds|None, error_reason)."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        return None, "google-auth не установлен (pip install google-auth google-auth-oauthlib)"

    creds_file = _credentials_path()
    token_file = _token_path()
    creds = None

    try:
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), GOOGLE_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
    except Exception as exc:
        return None, f"ошибка токена: {exc}"

    if creds and creds.valid:
        return creds, ""

    if interactive:
        ok, reason = run_oauth_flow()
        if ok:
            return get_google_credentials(interactive=False)
        return None, reason

    if not creds_file.exists():
        return None, f"OAuth credentials не найден: {creds_file}"
    return None, (
        f"нужна авторизация Google: запусти "
        f"python3 -m pds_ultimate.integrations.gmail_auth "
        f"(token → {token_file})"
    )


def run_oauth_flow() -> tuple[bool, str]:
    """One-time browser OAuth. Saves token to config.gmail.token_file."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return False, "google-auth-oauthlib не установлен"

    creds_file = _credentials_path()
    if not creds_file.exists():
        return False, f"credentials не найден: {creds_file}"

    token_file = _token_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Google OAuth OK → {token_file}")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def build_google_service(api: str, version: str, *, interactive: bool = False):
    """Build a Google API service. Returns (service|None, reason)."""
    creds, reason = get_google_credentials(interactive=interactive)
    if not creds:
        return None, reason
    try:
        from googleapiclient.discovery import build

        svc = build(api, version, credentials=creds, cache_discovery=False)
        return svc, ""
    except Exception as exc:
        return None, str(exc)
