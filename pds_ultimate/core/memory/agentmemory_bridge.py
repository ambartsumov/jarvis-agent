"""Optional bridge to agentmemory (https://github.com/rohitg00/agentmemory) via JSONL export."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pds_ultimate.config import DATA_DIR, config, logger


class AgentMemoryBridge:
    """
    Export observations to JSONL for agentmemory MCP / external tools.
    Does not require Node at runtime — file-based sync.
    """

    def __init__(self, enabled: bool | None = None) -> None:
        self.enabled = enabled if enabled is not None else config.memory.agentmemory_export
        self.export_dir = DATA_DIR / "agentmemory"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.export_dir / "observations.jsonl"

    def observe(self, session_id: str, role: str, content: str, user_id: int) -> None:
        if not self.enabled:
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content[:8000],
            "source": "pds-ultimate",
        }
        try:
            with self.export_dir.joinpath("observations.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.debug(f"AgentMemory export: {exc}")

    @staticmethod
    def mcp_config_snippet() -> dict:
        return {
            "agentmemory": {
                "command": "npx",
                "args": ["-y", "@agentmemory/mcp"],
            }
        }


agentmemory_bridge = AgentMemoryBridge()
