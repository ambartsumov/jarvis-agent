"""
PDS-Ultimate — thin backend: memory + OpenManus bridge only.
Telegram/channels → OpenClaw. Agent brain → OpenManus. No PDS tool orchestration.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import sys
from pathlib import Path

from pds_ultimate.config import AGENT_DISPLAY, DATA_DIR, config, logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_LOCK_FD = None


def _python_bin() -> str:
    """Real Python binary — Cursor rewrites sys.executable to AppImage."""
    override = os.environ.get("PYTHON_BIN", "").strip()
    if override and os.path.isfile(override):
        return override
    exe = sys.executable
    if "cursor" in exe.lower() or exe.endswith("AppImage"):
        for candidate in ("/usr/bin/python3.12", "/usr/bin/python3"):
            if os.path.isfile(candidate):
                return candidate
    return exe


def _acquire_single_instance_lock() -> None:
    global _LOCK_FD
    lock_path = DATA_DIR / ".agent.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FD = open(lock_path, "w")
    try:
        fcntl.flock(_LOCK_FD.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error(
            "Another agent instance is running (lock: %s). Stop it: pkill -f pds_ultimate.main",
            lock_path,
        )
        sys.exit(1)
    _LOCK_FD.write(str(os.getpid()))
    _LOCK_FD.flush()


async def _start_manus_bridge() -> asyncio.subprocess.Process | None:
    import sys as _sys

    pds_root = Path(__file__).resolve().parent
    agent_root = pds_root.parent
    manus_root = pds_root / "OpenManus-main"
    if not manus_root.is_dir():
        logger.warning("  ⚠ OpenManus-main not found")
        return None

    # Ensure OpenManus config exists (DeepSeek + PDS memory MCP)
    gen_script = pds_root / "scripts" / "gen_openmanus_config.py"
    if gen_script.is_file():
        import subprocess

        py = _python_bin()
        subprocess.run(
            [py, str(gen_script)],
            env={**os.environ, "PYTHON_BIN": py, "PDS_ULTIMATE_DIR": str(pds_root)},
            check=False,
            capture_output=True,
        )

    env = {
        **os.environ,
        "PYTHONPATH": f"{pds_root / '.venv' / 'lib' / 'python3.12' / 'site-packages'}:{agent_root}:{manus_root}",
        "PDS_ULTIMATE_DIR": str(pds_root),
    }
    host = os.environ.get("MANUS_BRIDGE_HOST", "127.0.0.1")
    port = os.environ.get("MANUS_BRIDGE_PORT", "8765")
    env.setdefault("MANUS_BRIDGE_HOST", host)
    env.setdefault("MANUS_BRIDGE_PORT", port)

    py = _python_bin()
    proc = await asyncio.create_subprocess_exec(
        py, "-m", "bridge.ws_server",
        cwd=str(manus_root), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await asyncio.sleep(1.2)
    if proc.returncode is not None:
        err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
        logger.error(f"  ❌ Manus bridge failed: {err[:500]}")
        return None
    logger.info(f"  🧠 OpenManus bridge: ws://{host}:{port}/manus (pid {proc.pid})")
    return proc


async def main() -> None:
    _acquire_single_instance_lock()
    logger.info("=" * 60)
    logger.info(f"  {AGENT_DISPLAY} — OpenManus + OpenClaw hybrid")
    logger.info("  PDS = memory only | Agent = OpenManus | Channels = OpenClaw")
    logger.info("=" * 60)

    for w in config.validate():
        logger.warning(f"  ⚠ {w}")

    logger.info("[1/3] Database (memory)...")
    from pds_ultimate.core.database import init_database

    engine, session_factory = init_database()

    from pds_ultimate.core.persona_engine import persona_engine
    from pds_ultimate.core.contacts.book import contact_book

    persona_engine.set_session_factory(session_factory)
    contact_book.set_session_factory(session_factory)

    logger.info("[2/3] OpenManus bridge...")
    manus_proc = await _start_manus_bridge()

    logger.info("[3/3] Ready")
    logger.info("  Full stack → bash pds_ultimate/scripts/start_system.sh")
    logger.info("  Or legacy PDS bot: unset OPENCLAW_TELEGRAM && python -m pds_ultimate.main")
    logger.info("=" * 60)

    # Hybrid default: OpenClaw owns Telegram unless explicitly disabled.
    openclaw_telegram = os.environ.get("OPENCLAW_TELEGRAM", "1").lower()
    if openclaw_telegram not in ("0", "false", "no", "off"):
        logger.info("OPENCLAW_TELEGRAM=1 — waiting (OpenClaw handles Telegram)")
        stop = asyncio.Event()
        try:
            await stop.wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
    else:
        # Legacy: PDS Telegram bot still works via hybrid agent → bridge
        from pds_ultimate.bot.setup import create_bot, start_polling

        logger.info("Starting PDS Telegram bot (hybrid → OpenManus)...")
        bot, dp = await create_bot(session_factory=session_factory)
        try:
            await start_polling(bot, dp)
        finally:
            pass

    if manus_proc and manus_proc.returncode is None:
        manus_proc.terminate()
        try:
            await asyncio.wait_for(manus_proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            manus_proc.kill()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
