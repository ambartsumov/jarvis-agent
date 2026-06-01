"""
Telethon auth - one-time setup.
Run: python telethon_auth.py
"""
import asyncio
import os
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from pathlib import Path

env_path = Path(__file__).parent / "pds_ultimate" / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

API_ID = int(os.environ.get("TG_API_ID", "0"))
API_HASH = os.environ.get("TG_API_HASH", "")
PHONE = os.environ.get("TG_PHONE", "")
SESSION = os.environ.get("TG_SESSION_NAME", "pds_userbot")

if not API_ID or not API_HASH:
    print("ERROR: TG_API_ID and TG_API_HASH not set in .env")
    sys.exit(1)

print(f"API_ID : {API_ID}")
print(f"Phone  : {PHONE}")
print(f"Session: {SESSION}")
print()


async def main():
    from telethon import TelegramClient

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized: {me.first_name} (@{me.username or 'N/A'})")
        await client.disconnect()
        return

    # Send code
    phone = PHONE or input("Phone number (e.g. +99365842520): ").strip()
    await client.send_code_request(phone)
    print(f"Code sent to {phone}. Enter it below:")

    code = input("Code: ").strip()
    try:
        await client.sign_in(phone, code)
    except Exception as e:
        if "two-steps" in str(e).lower() or "password" in str(e).lower():
            pwd = input("2FA password: ").strip()
            from telethon.errors import SessionPasswordNeededError
            await client.sign_in(password=pwd)
        else:
            raise

    me = await client.get_me()
    print(f"\nAuthorized: {me.first_name} {me.last_name or ''} (@{me.username or 'N/A'})")
    print(f"Session saved: {SESSION}.session")
    await client.disconnect()


asyncio.run(main())
