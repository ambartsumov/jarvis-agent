"""Linux desktop control — terminal first, GUI last. Manus integration layer."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from app.integrations.env_config import SUDO_PASSWORD

_USER_FILES = Path(os.environ.get("PDS_ULTIMATE_DIR", "")) / \
    "data" / "user_files"
if not _USER_FILES.exists():
    _USER_FILES = Path.home() / ".manus_files"
_USER_FILES.mkdir(parents=True, exist_ok=True)


def _gui_env() -> dict:
    env = dict(os.environ)
    uid = os.getuid()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    if "WAYLAND_DISPLAY" not in env:
        for cand in ("wayland-0", "wayland-1"):
            if Path(f"/run/user/{uid}/{cand}").exists():
                env["WAYLAND_DISPLAY"] = cand
                break
    env.setdefault("DBUS_SESSION_BUS_ADDRESS",
                   f"unix:path=/run/user/{uid}/bus")
    return env


def bootstrap_gui_env() -> None:
    for k, v in _gui_env().items():
        if v:
            os.environ.setdefault(k, v)


async def run_shell(cmd: str, *, sudo: bool = False, timeout: int = 90) -> tuple[bool, str]:
    env = _gui_env()
    if sudo:
        if not SUDO_PASSWORD:
            return False, "SUDO_PASSWORD not set in .env"
        cmd = f"echo {SUDO_PASSWORD!r} | sudo -S -p '' bash -lc {cmd!r}"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        text = (out or b"").decode("utf-8", "replace").strip()
        return proc.returncode == 0, text or "(empty)"
    except asyncio.TimeoutError:
        return False, f"timeout {timeout}s"
    except Exception as exc:
        return False, str(exc)


async def spawn(cmd: str) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, env=_gui_env(), start_new_session=True,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)
        if proc.returncode not in (None, 0):
            return False, f"launch failed: {cmd}"
        return True, f"OK: launched {cmd.split()[0]}"
    except Exception as exc:
        return False, str(exc)


_APP_DIRS = [
    "/usr/share/applications",
    str(Path.home() / ".local/share/applications"),
    "/var/lib/snapd/desktop/applications",
]


def _find_app(name: str) -> str | None:
    q = name.lower().strip()
    for d in _APP_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in p.glob("*.desktop"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if q in text.lower() or q in f.stem.lower():
                for line in text.splitlines():
                    if line.startswith("Exec="):
                        exec_line = line[5:].split("%")[0].strip()
                        return exec_line
    # common fallbacks
    fallbacks = {
        "telegram": "telegram-desktop",
        "cursor": "cursor",
        "chrome": "chromium",
        "chromium": "chromium",
        "firefox": "firefox",
        "editor": "gnome-text-editor",
        "music": "rhythmbox",
    }
    for key, bin_name in fallbacks.items():
        if key in q and shutil.which(bin_name):
            return bin_name
    return None


async def open_app(name: str) -> tuple[bool, str]:
    exec_line = _find_app(name)
    if not exec_line:
        return await spawn(f"gtk-launch {shlex.quote(name)} 2>/dev/null || xdg-open {shlex.quote(name)}")
    return await spawn(exec_line + " &")


async def open_url(url: str) -> tuple[bool, str]:
    return await spawn(f"xdg-open {shlex.quote(url)} &")


async def chrome_profile(profile: str) -> tuple[bool, str]:
    prof = profile.strip()
    if prof.lower() in ("work", "ворк", "рабоч"):
        prof = "Work"
    cmd = f"chromium --profile-directory={shlex.quote(prof)} %U &"
    if shutil.which("google-chrome"):
        cmd = f"google-chrome --profile-directory={shlex.quote(prof)} %U &"
    return await spawn(cmd)


async def music_play() -> tuple[bool, str]:
    await spawn("rhythmbox &")
    ok, out = await run_shell("rhythmbox-client --play 2>/dev/null || playerctl play 2>/dev/null")
    return ok, out or "OK: music"


async def volume(action: str) -> tuple[bool, str]:
    if action in ("up", "громче", "+"):
        return await run_shell("pactl set-sink-volume @DEFAULT_SINK@ +5%")
    if action in ("down", "тише", "-"):
        return await run_shell("pactl set-sink-volume @DEFAULT_SINK@ -5%")
    return await run_shell("pactl get-sink-volume @DEFAULT_SINK@")


async def screenshot(path: str | None = None) -> tuple[bool, str]:
    out = path or str(_USER_FILES / "screenshot.png")
    ok, msg = await run_shell(f"gnome-screenshot -f {shlex.quote(out)} || scrot {shlex.quote(out)}")
    return ok, f"OK: {out}" if ok else msg


async def edit_text(content: str) -> tuple[bool, str]:
    path = _USER_FILES / "note.txt"
    path.write_text(content, encoding="utf-8")
    read_back = path.read_text(encoding="utf-8")
    if read_back.strip() != content.strip():
        return False, "write verification failed"
    ok, msg = await open_app("gnome-text-editor")
    if not ok:
        ok, msg = await spawn(f"xdg-open {shlex.quote(str(path))} &")
    return True, f"OK: wrote {len(content)} chars → {path}"


async def where_am_i() -> tuple[bool, str]:
    ok, procs = await run_shell(
        "pgrep -a chromium|head -3; pgrep -a telegram|head -1; pgrep -a cursor|head -1; "
        "pgrep -a rhythmbox|head -1; wmctrl -l 2>/dev/null|head -8"
    )
    return ok, procs or "no windows detected"


async def notify(title: str, body: str = "") -> tuple[bool, str]:
    t = shlex.quote(title or "Джарвис")
    b = shlex.quote(body or "")
    ok, msg = await run_shell(f"notify-send {t} {b} 2>/dev/null || echo {b}")
    return ok, msg or f"OK: {title}"


async def clipboard(action: str, text: str = "") -> tuple[bool, str]:
    act = (action or "get").lower()
    if act in ("get", "read"):
        ok, out = await run_shell(
            "wl-paste 2>/dev/null || xclip -selection clipboard -o 2>/dev/null"
        )
        return ok, out or "(clipboard empty)"
    if act in ("set", "write"):
        if not text:
            return False, "content required for clipboard set"
        quoted = shlex.quote(text)
        ok, msg = await run_shell(
            f"printf %s {quoted} | wl-copy 2>/dev/null || "
            f"printf %s {quoted} | xclip -selection clipboard 2>/dev/null"
        )
        return ok, msg or "OK: clipboard set"
    return False, "clipboard action: get or set"


async def kill_app(name: str) -> tuple[bool, str]:
    if not name.strip():
        return False, "target required"
    pat = shlex.quote(name.strip())
    await run_shell(f"pkill -f {pat} 2>/dev/null || true")
    ok, msg = await run_shell(f"pgrep -a {pat}|head -3")
    if ok and msg.strip():
        return False, f"still running: {msg}"
    return True, f"OK: stopped {name}"


async def focus_window(title: str) -> tuple[bool, str]:
    if not title.strip():
        return False, "target window title required"
    q = shlex.quote(title.strip())
    ok, msg = await run_shell(f"wmctrl -a {q} 2>/dev/null || xdotool search --name {q} windowactivate 2>/dev/null")
    return ok, msg or f"OK: focused {title}"


# ─── xdotool/ydotool — Human-like mouse & keyboard at max speed ───────────────

async def mouse_move(x: int, y: int) -> tuple[bool, str]:
    """Move mouse to absolute screen coordinates."""
    return await run_shell(f"xdotool mousemove {x} {y}")


async def mouse_click(x: int, y: int, button: int = 1, count: int = 1) -> tuple[bool, str]:
    """Click at (x,y). button: 1=left 2=mid 3=right. count=2 = double-click."""
    clicks = " ".join([f"click {button}"] * max(1, count))
    ok, msg = await run_shell(f"xdotool mousemove --sync {x} {y} {clicks}")
    return ok, msg or f"OK: click({x},{y})"


async def double_click(x: int, y: int) -> tuple[bool, str]:
    return await mouse_click(x, y, button=1, count=2)


async def right_click(x: int, y: int) -> tuple[bool, str]:
    return await mouse_click(x, y, button=3)


async def human_type(text: str, delay_ms: int = 0) -> tuple[bool, str]:
    """Type text at maximum speed via xdotool (delay_ms=0 → instant)."""
    ok, msg = await run_shell(f"xdotool type --delay {delay_ms} --clearmodifiers {shlex.quote(text)}")
    return ok, msg or f"OK: typed {len(text)} chars"


async def key_press(keys: str) -> tuple[bool, str]:
    """Press key or combo: ctrl+c, super, Return, F5, ctrl+shift+i, etc."""
    return await run_shell(f"xdotool key {shlex.quote(keys)}")


async def scroll_at(x: int, y: int, direction: str = "down", amount: int = 3) -> tuple[bool, str]:
    """Scroll at position (x,y). direction: up/down, amount: wheel ticks."""
    btn = 5 if direction.lower() in ("down", "вниз", "dn") else 4
    clicks = " ".join([f"click {btn}"] * max(1, amount))
    ok, msg = await run_shell(f"xdotool mousemove --sync {x} {y} {clicks}")
    return ok, msg or f"OK: scroll {direction}×{amount} at ({x},{y})"


async def drag_drop(x1: int, y1: int, x2: int, y2: int) -> tuple[bool, str]:
    """Drag from (x1,y1) to (x2,y2)."""
    cmd = (
        f"xdotool mousemove --sync {x1} {y1} mousedown 1 "
        f"mousemove --sync {x2} {y2} mouseup 1"
    )
    ok, msg = await run_shell(cmd)
    return ok, msg or f"OK: drag ({x1},{y1})→({x2},{y2})"


async def get_screen_size() -> tuple[bool, str]:
    """Return display width×height in pixels."""
    return await run_shell("xdotool getdisplaygeometry")


async def get_mouse_pos() -> tuple[bool, str]:
    """Return current cursor position."""
    return await run_shell("xdotool getmouselocation --shell")


async def get_active_window() -> tuple[bool, str]:
    """Return active window id, title, and geometry."""
    ok, wid = await run_shell("xdotool getactivewindow 2>/dev/null")
    if ok and wid.strip():
        _, name = await run_shell(f"xdotool getwindowname {wid.strip()} 2>/dev/null")
        _, geom = await run_shell(f"xdotool getwindowgeometry {wid.strip()} 2>/dev/null")
        return True, f"id={wid.strip()}\ntitle={name}\n{geom}"
    return await run_shell("wmctrl -l 2>/dev/null | head -5")


async def window_activate(query: str) -> tuple[bool, str]:
    """Find visible window by name/title and bring it to front."""
    q = shlex.quote(query.strip())
    ok, wid = await run_shell(f"xdotool search --onlyvisible --name {q} 2>/dev/null | head -1")
    if ok and wid.strip():
        await run_shell(f"xdotool windowactivate --sync {wid.strip()}")
        return True, f"OK: activated window {wid.strip()} ({query})"
    ok2, msg2 = await run_shell(f"wmctrl -a {q} 2>/dev/null")
    return ok2, msg2 or f"window '{query}' not found"


async def read_file_root(path: str) -> tuple[bool, str]:
    """Read any file; tries sudo for protected paths."""
    ok, out = await run_shell(f"cat {shlex.quote(path)}")
    if not ok:
        ok, out = await run_shell(f"cat {shlex.quote(path)}", sudo=True)
    return ok, out


async def write_file_root(path: str, content: str) -> tuple[bool, str]:
    """Write to any file; uses sudo if direct write fails."""
    import tempfile as _tempfile
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return True, f"OK: wrote {len(content)} chars → {path}"
    except (PermissionError, OSError):
        pass
    with _tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False, encoding="utf-8") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    ok, msg = await run_shell(f"mv {shlex.quote(tmp_path)} {shlex.quote(path)}", sudo=True)
    return ok, msg or f"OK: wrote {len(content)} chars → {path}"


async def run_root(command: str) -> tuple[bool, str]:
    """Execute any shell command as root (sudo). Built-in password."""
    return await run_shell(command, sudo=True)


async def find_files(pattern: str, root_dir: str = "/home") -> tuple[bool, str]:
    """Find files by name pattern."""
    return await run_shell(
        f"find {shlex.quote(root_dir)} -name {shlex.quote(pattern)} -maxdepth 8 2>/dev/null | head -30"
    )


async def get_ports() -> tuple[bool, str]:
    """List all listening TCP/UDP ports."""
    ok, out = await run_shell("ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null")
    return ok, out


async def get_user_info() -> tuple[bool, str]:
    """Get current user and system info."""
    ok, out = await run_shell("id && echo '---' && whoami && echo '---' && uname -a")
    return ok, out


# ── OCR (Tesseract) ───────────────────────────────────────────────────────────

async def screen_ocr(path: str | None = None) -> tuple[bool, str]:
    """
    Read text from screen using Tesseract OCR.
    If path is None, takes a screenshot first then OCR's it.
    Supports Russian and English text.
    """
    import tempfile

    target_path = path
    tmp_file = None

    if not target_path:
        # Auto-screenshot
        tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_file.close()
        target_path = tmp_file.name
        ok, err = await screenshot(target_path)
        if not ok:
            return False, f"OCR screenshot failed: {err}"

    try:
        ok, text = await run_shell(
            f"tesseract {shlex.quote(target_path)} stdout -l rus+eng 2>/dev/null"
        )
        if not ok and not text.strip():
            ok, text = await run_shell(
                f"tesseract {shlex.quote(target_path)} stdout -l eng 2>/dev/null"
            )
        result = text.strip()
        return True, result if result else "(no text found)"
    finally:
        if tmp_file:
            try:
                import os as _os
                _os.unlink(tmp_file.name)
            except Exception:
                pass


# ── Macro recorder / replayer ─────────────────────────────────────────────────

def _macros_dir() -> "Path":
    import os as _os
    from pathlib import Path as _Path
    d = _Path(_os.environ.get("PDS_ULTIMATE_DIR", ".")) / "data" / "macros"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def macro_record(name: str, steps: list[dict]) -> tuple[bool, str]:
    """
    Save a macro (list of desktop action steps) to disk for later replay.
    Each step is a dict: {"action": "...", ...kwargs...}
    Example steps: [{"action":"mouse_click","x":100,"y":200}, {"action":"type_text","text":"hello"}]
    """
    import json as _json

    if not steps:
        return False, "steps list is empty — provide at least one action step"
    macro_file = _macros_dir() / f"{name}.json"
    data = {
        "name": name,
        "steps": steps,
        "created": datetime.utcnow().isoformat(),
    }
    macro_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2))
    return True, f"Macro '{name}' saved ({len(steps)} steps) → {macro_file}"


async def macro_replay(name: str, speed_multiplier: float = 1.0) -> tuple[bool, str]:
    """
    Replay a saved macro step by step.
    speed_multiplier: 1.0 = normal, 2.0 = 2× faster (shorter delays), 0.5 = slower.
    """
    import json as _json

    macro_file = _macros_dir() / f"{name}.json"
    if not macro_file.exists():
        available = [f.stem for f in _macros_dir().glob("*.json")]
        return False, (
            f"Macro '{name}' not found. Available: {available or '(none)'}"
        )

    data = _json.loads(macro_file.read_text())
    steps = data.get("steps", [])
    if not steps:
        return False, f"Macro '{name}' has no steps"

    results = []
    for i, step in enumerate(steps):
        action = step.get("action", "")
        params = {k: v for k, v in step.items(
        ) if k not in ("action", "delay_ms")}
        delay_ms = step.get("delay_ms", 0)

        ok, out = await dispatch(action, **params)
        results.append(
            f"[{i+1}/{len(steps)}] {action}: {'✓' if ok else '✗'} {out[:100]}")

        if delay_ms > 0 and speed_multiplier > 0:
            adjusted = delay_ms / speed_multiplier / 1000.0
            if adjusted > 0.01:
                await asyncio.sleep(min(adjusted, 5.0))

    summary = f"Macro '{name}' replayed {len(steps)} steps"
    failed = sum(1 for r in results if "✗" in r)
    if failed:
        summary += f" ({failed} failed)"
    return failed == 0, summary + "\n" + "\n".join(results)


async def dispatch(action: str, **kwargs) -> tuple[bool, str]:
    action = (action or "").lower().strip()
    target = kwargs.get("target", "") or kwargs.get(
        "url", "") or kwargs.get("app", "")

    if action in ("run", "exec", "cmd", "shell"):
        return await run_shell(kwargs.get("command", target))
    if action in ("open_app", "app", "launch"):
        return await open_app(target or kwargs.get("name", ""))
    if action in ("open_url", "url"):
        return await open_url(target or kwargs.get("url", ""))
    if action in ("chrome_profile", "browser_profile"):
        return await chrome_profile(target or "Default")
    if action in ("music", "play_music"):
        return await music_play()
    if action == "volume":
        return await volume(kwargs.get("direction", target or "up"))
    if action in ("screenshot", "screen"):
        return await screenshot(kwargs.get("path"))
    if action in ("edit_text", "text_editor"):
        return await edit_text(kwargs.get("content", target))
    if action in ("where_am_i", "context"):
        return await where_am_i()
    if action in ("notify", "notification"):
        return await notify(kwargs.get("title", target), kwargs.get("content", kwargs.get("body", "")))
    if action == "clipboard":
        return await clipboard(kwargs.get("direction", target or "get"), kwargs.get("content", kwargs.get("text", "")))
    if action in ("kill_app", "kill"):
        return await kill_app(target or kwargs.get("name", ""))
    if action in ("focus_window", "focus"):
        return await focus_window(target or kwargs.get("name", ""))

    # ── xdotool human-like control ──────────────────────────────────────────
    if action in ("mouse_move", "move_mouse", "move"):
        return await mouse_move(int(kwargs.get("x", 0)), int(kwargs.get("y", 0)))
    if action in ("mouse_click", "click", "left_click"):
        return await mouse_click(
            int(kwargs.get("x", 0)), int(kwargs.get("y", 0)),
            button=int(kwargs.get("button", 1)), count=int(kwargs.get("count", 1)),
        )
    if action in ("double_click", "dblclick"):
        return await double_click(int(kwargs.get("x", 0)), int(kwargs.get("y", 0)))
    if action in ("right_click", "context_menu"):
        return await right_click(int(kwargs.get("x", 0)), int(kwargs.get("y", 0)))
    if action in ("type_text", "type", "human_type", "keyboard_type", "input"):
        text = kwargs.get("text", kwargs.get("content", target or ""))
        delay = int(kwargs.get("delay", 0))
        return await human_type(text, delay_ms=delay)
    if action in ("key_press", "hotkey", "key", "keyboard", "press_key"):
        return await key_press(kwargs.get("keys", kwargs.get("key", target or "")))
    if action in ("scroll", "scroll_at", "page_scroll"):
        return await scroll_at(
            int(kwargs.get("x", 0)), int(kwargs.get("y", 0)),
            direction=kwargs.get("direction", "down"),
            amount=int(kwargs.get("amount", 3)),
        )
    if action in ("drag", "drag_drop", "drag_and_drop"):
        return await drag_drop(
            int(kwargs.get("x1", 0)), int(kwargs.get("y1", 0)),
            int(kwargs.get("x2", 0)), int(kwargs.get("y2", 0)),
        )
    if action in ("screen_size", "display_size", "get_screen_size", "resolution"):
        return await get_screen_size()
    if action in ("mouse_pos", "get_mouse_pos", "cursor_pos"):
        return await get_mouse_pos()
    if action in ("active_window", "get_active_window", "current_window"):
        return await get_active_window()
    if action in ("window_activate", "window_focus", "find_window"):
        return await window_activate(target or kwargs.get("name", ""))
    if action in ("read_file", "cat_file", "file_read", "view_file"):
        return await read_file_root(kwargs.get("path", target or ""))
    if action in ("write_file", "file_write", "save_file", "write_to_file"):
        return await write_file_root(
            kwargs.get("path", target or ""), kwargs.get("content", "")
        )
    if action in ("run_root", "sudo", "run_as_root", "root_exec", "root"):
        return await run_root(kwargs.get("command", target or ""))
    if action in ("find_files", "locate_files", "search_files"):
        return await find_files(
            kwargs.get("pattern", target or "*"),
            kwargs.get("root_dir", kwargs.get("path", "/home")),
        )
    if action in ("ports", "port_scan", "open_ports", "netstat"):
        return await get_ports()
    if action in ("user_info", "whoami", "id", "system_info"):
        return await get_user_info()
    if action in ("screen_ocr", "ocr", "read_screen", "ocr_screenshot"):
        return await screen_ocr(kwargs.get("path"))
    if action in ("macro_record", "record_macro", "save_macro"):
        return await macro_record(
            kwargs.get("name", target or "default"),
            kwargs.get("steps", []),
        )
    if action in ("macro_replay", "replay_macro", "run_macro", "play_macro"):
        return await macro_replay(
            kwargs.get("name", target or "default"),
            float(kwargs.get("speed", kwargs.get("speed_multiplier", 1.0))),
        )

    return False, (
        f"unknown action: {action}. "
        "Use: run, open_app, open_url, chrome_profile, music, volume, screenshot, "
        "edit_text, where_am_i, notify, clipboard, kill_app, focus_window | "
        "mouse_move, mouse_click, double_click, right_click, type_text, key_press, "
        "scroll, drag_drop, screen_size, mouse_pos, active_window, window_activate | "
        "read_file, write_file, run_root, find_files, ports, user_info | "
        "screen_ocr, macro_record, macro_replay"
    )
