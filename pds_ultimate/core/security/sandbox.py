"""Docker-based sandbox for high-risk execution (shell/python) for non-owner users."""

from __future__ import annotations

import asyncio
import shutil

from pds_ultimate.config import logger

_DOCKER_AVAILABLE: bool | None = None


def docker_available() -> bool:
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is None:
        _DOCKER_AVAILABLE = shutil.which("docker") is not None
    return _DOCKER_AVAILABLE


async def run_in_sandbox(command: str, *, timeout: int = 60, image: str = "python:3.12-slim") -> tuple[bool, str]:
    """
    Run a shell command inside an ephemeral, network-isolated Docker container.
    Falls back to a hard refusal if Docker is unavailable.
    """
    if not docker_available():
        return False, "Sandbox unavailable (Docker not installed). Команда отклонена для не-владельца."

    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--memory", "256m",
        "--cpus", "0.5",
        "--pids-limit", "128",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        "--workdir", "/tmp",
        image,
        "sh", "-c", command,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 15)
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        success = proc.returncode == 0
        combined = out + (f"\n[stderr]\n{err}" if err else "")
        return success, combined.strip() or "(empty)"
    except asyncio.TimeoutError:
        return False, f"Sandbox timeout after {timeout}s"
    except Exception as exc:
        logger.warning(f"Sandbox error: {exc}")
        return False, f"Sandbox error: {exc}"
