"""StrReplaceEditor — precise file editing via string replacement.

Adapted from OpenManus app/tool/str_replace_editor.py for pds_ultimate.
Key feature: edit files by matching an exact string — avoids wrong-line replacements.

Commands: view, create, str_replace, insert, undo_edit
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pds_ultimate.config import BASE_DIR, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry

_WORKSPACE = BASE_DIR.parent  # /agent or project root
_SNIPPET_LINES = 4
_MAX_RESPONSE = 16_000
_TRUNCATED_NOTE = (
    "\n<NOTE: output truncated — use grep -n to find exact line numbers></NOTE>"
)

# Per-file undo history: path → list of previous contents
_undo_history: dict[str, list[str]] = defaultdict(list)


def _truncate(content: str) -> str:
    if len(content) <= _MAX_RESPONSE:
        return content
    return content[:_MAX_RESPONSE] + _TRUNCATED_NOTE


def _resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _WORKSPACE / p
    return p.resolve()


# ── command implementations ───────────────────────────────────────────────────

def _cmd_view(path: Path) -> str:
    if path.is_dir():
        lines: list[str] = []
        for root, dirs, files in os.walk(path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            depth = Path(root).relative_to(path).parts
            if len(depth) > 2:
                continue
            indent = "  " * len(depth)
            lines.append(f"{indent}{Path(root).name}/")
            for f in sorted(files):
                if not f.startswith("."):
                    lines.append(f"{indent}  {f}")
        return _truncate("\n".join(lines))

    if not path.exists():
        return f"Error: {path} does not exist"

    content = path.read_text(encoding="utf-8", errors="replace")
    numbered = "\n".join(f"{i+1:4d}\t{line}" for i,
                         line in enumerate(content.splitlines()))
    return _truncate(numbered)


def _cmd_create(path: Path, file_text: str) -> str:
    if path.exists():
        return f"Error: {path} already exists. Use str_replace to modify it."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(file_text, encoding="utf-8")
    lines = len(file_text.splitlines())
    return f"Created {path} ({lines} lines)"


def _cmd_str_replace(path: Path, old_str: str, new_str: str) -> str:
    if not path.exists():
        return f"Error: {path} does not exist"

    content = path.read_text(encoding="utf-8", errors="replace")
    occurrences = content.count(old_str)

    if occurrences == 0:
        return f"Error: old_str not found in {path}. Ensure whitespace/indentation matches exactly."
    if occurrences > 1:
        return (
            f"Error: old_str found {occurrences} times in {path}. "
            "Include more context to make it unique."
        )

    # Save undo state
    _undo_history[str(path)].append(content)

    new_content = content.replace(old_str, new_str, 1)
    path.write_text(new_content, encoding="utf-8")

    # Show snippet around change
    old_lines = old_str.splitlines()
    new_lines = new_str.splitlines()
    insert_line = content[: content.index(old_str)].count("\n")

    snippet_start = max(0, insert_line - _SNIPPET_LINES)
    snippet_end = insert_line + len(new_lines) + _SNIPPET_LINES
    snippet = "\n".join(
        f"{i+1:4d}\t{line}"
        for i, line in enumerate(new_content.splitlines()[snippet_start:snippet_end], start=snippet_start)
    )
    return f"Replaced {len(old_lines)} line(s) with {len(new_lines)} line(s) in {path}:\n{snippet}"


def _cmd_insert(path: Path, insert_line: int, new_str: str) -> str:
    if not path.exists():
        return f"Error: {path} does not exist"

    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    if insert_line < 0 or insert_line > len(lines):
        return f"Error: insert_line {insert_line} out of range (file has {len(lines)} lines)"

    # Save undo state
    _undo_history[str(path)].append(content)

    new_lines = [
        l + "\n" if not l.endswith("\n") else l for l in new_str.splitlines()]
    lines[insert_line:insert_line] = new_lines
    path.write_text("".join(lines), encoding="utf-8")

    snippet_start = max(0, insert_line - _SNIPPET_LINES)
    snippet_end = insert_line + len(new_lines) + _SNIPPET_LINES
    snippet = "\n".join(
        f"{i+1:4d}\t{l.rstrip()}"
        for i, l in enumerate(lines[snippet_start:snippet_end], start=snippet_start)
    )
    return f"Inserted {len(new_lines)} line(s) at line {insert_line + 1} in {path}:\n{snippet}"


def _cmd_undo_edit(path: Path) -> str:
    history = _undo_history.get(str(path))
    if not history:
        return f"Error: no undo history for {path}"

    previous = history.pop()
    path.write_text(previous, encoding="utf-8")
    return f"Reverted {path} to previous state ({len(previous.splitlines())} lines)"


# ── unified handler ───────────────────────────────────────────────────────────

async def _str_replace_editor_handler(
    command: str,
    path: str,
    file_text: Optional[str] = None,
    old_str: Optional[str] = None,
    new_str: Optional[str] = None,
    insert_line: Optional[int] = None,
) -> ToolResult:
    try:
        resolved = _resolve_path(path)

        if command == "view":
            out = _cmd_view(resolved)
            return ToolResult(success=True, output=out)

        elif command == "create":
            if file_text is None:
                return ToolResult(success=False, output="", error="file_text is required for create")
            out = _cmd_create(resolved, file_text)
            return ToolResult(success=True, output=out)

        elif command == "str_replace":
            if old_str is None:
                return ToolResult(success=False, output="", error="old_str is required for str_replace")
            out = _cmd_str_replace(resolved, old_str, new_str or "")
            success = not out.startswith("Error")
            return ToolResult(success=success, output="" if not success else out, error=out if not success else "")

        elif command == "insert":
            if new_str is None or insert_line is None:
                return ToolResult(success=False, output="", error="new_str and insert_line are required for insert")
            out = _cmd_insert(resolved, insert_line, new_str)
            success = not out.startswith("Error")
            return ToolResult(success=success, output="" if not success else out, error=out if not success else "")

        elif command == "undo_edit":
            out = _cmd_undo_edit(resolved)
            success = not out.startswith("Error")
            return ToolResult(success=success, output="" if not success else out, error=out if not success else "")

        else:
            return ToolResult(success=False, output="", error=f"Unknown command: {command}")

    except Exception as exc:
        logger.error(f"str_replace_editor error: {exc}")
        return ToolResult(success=False, output="", error=str(exc))


# ── registration ──────────────────────────────────────────────────────────────

_STR_REPLACE_EDITOR_SPEC = ToolSpec(
    name="str_replace_editor",
    description=(
        "Precise file editing by matching exact strings. "
        "Commands: view (show file with line numbers), create (new file), "
        "str_replace (replace unique string), insert (insert at line), undo_edit (revert last change). "
        "str_replace ONLY works if old_str appears exactly once — include enough context to be unique."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                "description": "Operation to perform",
            },
            "path": {
                "type": "string",
                "description": "File or directory path (absolute or relative to workspace)",
            },
            "file_text": {
                "type": "string",
                "description": "Full content for 'create' command",
            },
            "old_str": {
                "type": "string",
                "description": "Exact string to replace (must be unique in file) for 'str_replace'",
            },
            "new_str": {
                "type": "string",
                "description": "Replacement string for 'str_replace' or new lines for 'insert'",
            },
            "insert_line": {
                "type": "integer",
                "description": "0-based line number to insert after for 'insert' command",
            },
        },
        "required": ["command", "path"],
    },
    handler=_str_replace_editor_handler,
    category="files",
    risk="medium",
)


def register_str_replace_editor() -> None:
    """Register the str_replace_editor tool in the global registry."""
    tool_registry.register(_STR_REPLACE_EDITOR_SPEC)
    logger.debug("str_replace_editor tool registered")
