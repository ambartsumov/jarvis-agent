"""Desktop control tool — Linux terminal-first + full xdotool human-like control."""

from __future__ import annotations

from app.integrations.desktop_linux import bootstrap_gui_env, dispatch
from app.tool.base import BaseTool, ToolResult

_DESKTOP_DESC = """Control the owner's Linux desktop at maximum speed and precision.

TERMINAL/SHELL ACTIONS (prefer these first):
- run: shell command (command=...)
- run_root / sudo: run as root with built-in sudo password (command=...)
- read_file: read any file (path=...); uses sudo for protected files
- write_file: write to any file (path=..., content=...); uses sudo if needed
- find_files: find files by name pattern (pattern=*.py, root_dir=/home)
- ports: list all open/listening ports
- user_info: current user, groups, system info

APP / GUI ACTIONS:
- open_app: launch app by name (target=telegram|cursor|chromium|...)
- open_url: open URL in default browser (url=...)
- open_file: open a FILE with its default app (path=...) — xlsx→LibreOffice Calc, docx→Writer, pdf→Evince, etc. USE THIS to open files.
- chrome_profile: open Chromium with profile (target=Work|Default)
- kill_app: kill app by name (target=...)
- where_am_i: list running apps/windows (call before any GUI action)
- active_window: get active window id, title, and geometry
- window_activate / find_window: bring window to front by title (target=...)
- focus_window: focus window by title (target=...)
- screenshot: capture screen → saves to file (path=... optional)

HUMAN-LIKE MOUSE CONTROL (xdotool — instant, max speed):
- mouse_move: move cursor to (x=..., y=...)
- mouse_click / click / left_click: click at (x=..., y=..., button=1, count=1)
- double_click: double-click at (x=..., y=...)
- right_click: right-click at (x=..., y=...)
- scroll: scroll at position (x=..., y=..., direction=up|down, amount=3)
- drag_drop: drag from (x1,y1) to (x2,y2)
- mouse_pos: get current cursor position
- screen_size: get display resolution

HUMAN-LIKE KEYBOARD CONTROL (xdotool — instant):
- type_text / input: type text into focused app (text=..., delay=0 for max speed)
- key_press / hotkey: press key or combo (keys=ctrl+c|Return|F5|super|ctrl+shift+i)

DESKTOP UTILITIES:
- music: play music via Rhythmbox/playerctl
- volume: adjust volume (direction=up|down)
- edit_text: write text to file and open editor (content=...)
- notify: desktop notification (title=..., content=...)
- clipboard: get/set clipboard (direction=get|set, content=...)

OCR & COMPUTER VISION:
- screen_ocr: read text from screen via Tesseract (path=... optional; if omitted, auto-screenshots)
  Returns extracted text in Russian + English.

MACRO AUTOMATION:
- macro_record: save a sequence of desktop actions (name=..., steps=[{action:..., ...}])
- macro_replay: replay a saved macro (name=..., speed=1.0)
  steps format: [{"action":"mouse_click","x":100,"y":200,"delay_ms":500}, ...]
"""


class DesktopTool(BaseTool):
    name: str = "desktop"
    description: str = _DESKTOP_DESC
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    # terminal/shell
                    "run", "run_root", "sudo", "read_file", "write_file",
                    "find_files", "ports", "user_info",
                    # app/gui
                    "open_app", "open_url", "open_file", "chrome_profile", "kill_app",
                    "where_am_i", "active_window", "window_activate", "find_window",
                    "focus_window", "screenshot",
                    # mouse
                    "mouse_move", "mouse_click", "click", "left_click",
                    "double_click", "right_click",
                    "scroll", "drag_drop", "mouse_pos", "screen_size",
                    # keyboard
                    "type_text", "input", "key_press", "hotkey",
                    # utilities
                    "music", "volume", "edit_text", "notify", "clipboard",
                    # OCR & macros
                    "screen_ocr", "macro_record", "macro_replay",
                ],
            },
            # shell / file
            "command": {"type": "string", "description": "Shell command for run/run_root"},
            "path": {"type": "string", "description": "File path for read_file/write_file/find_files"},
            "content": {"type": "string", "description": "Content for write_file / edit_text / clipboard set / notify body"},
            "pattern": {"type": "string", "description": "File name pattern for find_files"},
            "root_dir": {"type": "string", "description": "Root dir for find_files (default /home)"},
            # app/gui
            "target": {"type": "string", "description": "App name / window title / profile name"},
            "url": {"type": "string", "description": "URL for open_url"},
            # mouse
            "x": {"type": "integer", "description": "Screen X coordinate in pixels"},
            "y": {"type": "integer", "description": "Screen Y coordinate in pixels"},
            "x1": {"type": "integer", "description": "Drag start X"},
            "y1": {"type": "integer", "description": "Drag start Y"},
            "x2": {"type": "integer", "description": "Drag end X"},
            "y2": {"type": "integer", "description": "Drag end Y"},
            "button": {"type": "integer", "description": "Mouse button: 1=left 2=mid 3=right"},
            "count": {"type": "integer", "description": "Click count (2 = double-click)"},
            "amount": {"type": "integer", "description": "Scroll ticks (default 3)"},
            "direction": {"type": "string", "enum": ["up", "down", "get", "set"]},
            # keyboard
            "text": {"type": "string", "description": "Text to type (type_text action)"},
            "keys": {"type": "string", "description": "Key combo for key_press: ctrl+c, Return, F5, etc."},
            "delay": {"type": "integer", "description": "Typing delay in ms (0=max speed)"},
            # OCR
            "path": {"type": "string", "description": "File path for read_file/write_file/find_files/screen_ocr"},
            # macros
            "name": {"type": "string", "description": "Macro name for macro_record/macro_replay"},
            "steps": {"type": "array", "description": "List of action step dicts for macro_record"},
            "speed": {"type": "number", "description": "Speed multiplier for macro_replay (1.0=normal, 2.0=fast)"},
            # other
            "title": {"type": "string", "description": "Notification title"},
        },
        "required": ["action"],
    }

    async def execute(self, action: str, **kwargs) -> ToolResult:
        bootstrap_gui_env()
        ok, msg = await dispatch(action, **kwargs)
        if ok:
            return self.success_response(msg)
        return self.fail_response(msg)
