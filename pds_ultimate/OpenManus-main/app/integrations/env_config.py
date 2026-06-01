"""Load secrets from pds_ultimate/.env — single source for OpenManus + OpenClaw hybrid."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PDS_ROOT = Path(os.environ.get("PDS_ULTIMATE_DIR", Path(__file__).resolve().parents[3]))
load_dotenv(PDS_ROOT / ".env")

CREDENTIALS_DIR = PDS_ROOT / "credentials"
DATA_DIR = PDS_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SUDO_PASSWORD = os.getenv("SUDO_PASSWORD", "")
TIMEZONE = os.getenv("BROWSER_TIMEZONE", os.getenv("TZ", "Asia/Ashgabat"))

GMAIL_CREDENTIALS = Path(os.getenv("GMAIL_CREDENTIALS", str(CREDENTIALS_DIR / "gmail.json")))
GMAIL_TOKEN = Path(os.getenv("GMAIL_TOKEN", str(DATA_DIR / "gmail_token.json")))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
