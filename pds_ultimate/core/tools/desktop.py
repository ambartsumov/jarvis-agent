"""Desktop control — autonomous JARVIS-level control of the owner's PC.

PRIORITY: TERMINAL FIRST (Linux CLI), GUI (mouse/OCR) ONLY AS LAST RESORT.
Almost everything on Linux can be done via terminal: gtk-launch, xdg-open,
chromium --profile-directory, rhythmbox-client, playerctl, wmctrl, pactl, etc.
Use click_text/read_screen ONLY when CLI genuinely cannot do the job.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import struct
import time
from pathlib import Path

from pds_ultimate.config import USER_FILES_DIR, logger
from pds_ultimate.core.tools.base import ToolResult, ToolSpec
from pds_ultimate.core.tools.registry import tool_registry


def _gui_env() -> dict:
    env = dict(os.environ)
    uid = os.getuid()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    # Wayland socket (GNOME default)
    if "WAYLAND_DISPLAY" not in env:
        for cand in ("wayland-0", "wayland-1"):
            if Path(f"/run/user/{uid}/{cand}").exists():
                env["WAYLAND_DISPLAY"] = cand
                break
    env.setdefault("DBUS_SESSION_BUS_ADDRESS",
                   f"unix:path=/run/user/{uid}/bus")
    return env


def bootstrap_gui_env() -> None:
    """Ensure the agent process itself has a GUI session (needed when started via nohup/systemd)."""
    env = _gui_env()
    for key in ("DISPLAY", "XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        if key in env and env[key]:
            os.environ.setdefault(key, env[key])


_XDOTOOL = "/usr/bin/xdotool" if Path(
    "/usr/bin/xdotool").is_file() else (shutil.which("xdotool") or "")

# pgrep patterns for common GUI apps (Wayland-safe verification)
_GUI_PROC_PATTERNS: list[tuple[str, str, str]] = [
    ("Chromium", r"chromium-browser/chrome|/snap/chromium/"),
    ("Chrome", r"google-chrome"),
    ("Firefox", r"/firefox/firefox"),
    ("Telegram", r"telegram-desktop"),
    ("Cursor", r"cursor.AppImage|/share/cursor/cursor"),
    ("VS Code", r"/Code/code|/code/code"),
    ("Rhythmbox", r"rhythmbox"),
    ("Files", r"nautilus|org.gnome.Nautilus"),
    ("Terminal", r"gnome-terminal|konsole"),
    ("Text Editor", r"gnome-text-editor|org.gnome.TextEditor"),
]


async def _spawn(cmd: list[str] | str) -> tuple[bool, str]:
    """Launch a detached GUI process; detect immediate launch failures."""
    try:
        if isinstance(cmd, str):
            proc = await asyncio.create_subprocess_shell(
                cmd, env=_gui_env(), start_new_session=True,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd, env=_gui_env(), start_new_session=True,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
        # If the launcher exits non-zero within ~1.5s, the app did not start.
        for _ in range(6):
            rc = proc.returncode if proc.returncode is not None else proc.poll()
            if rc is not None:
                if rc != 0:
                    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
                    return False, f"launcher exit {rc}: {shown}"
                break
            await asyncio.sleep(0.25)
        shown = cmd if isinstance(cmd, str) else " ".join(cmd)
        return True, f"запущено: {shown}"
    except Exception as exc:
        return False, str(exc)


async def _run_capture(cmd: str, *, sudo: bool = False, timeout: int = 60) -> tuple[bool, str]:
    """Run a shell command and capture output. Optional root via sudo."""
    from pds_ultimate.config import SUDO_PASSWORD

    env = _gui_env()
    if sudo:
        if not SUDO_PASSWORD:
            return False, "SUDO_PASSWORD не задан в .env"
        cmd = f"echo {SUDO_PASSWORD!r} | sudo -S -p '' bash -lc {cmd!r}"
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        text = (out or b"").decode("utf-8", "replace").strip()
        # ydotool prints a harmless daemon notice on stderr→stdout; drop it
        text = "\n".join(l for l in text.splitlines()
                         if "ydotoold backend" not in l).strip()
        return proc.returncode == 0, text or "(пусто)"
    except asyncio.TimeoutError:
        return False, f"таймаут {timeout}s"
    except Exception as exc:
        return False, str(exc)


# ─── Input injection: xdotool (absolute coords, works on this GNOME session) ──
async def _xdotool(args: str, *, timeout: int = 15) -> tuple[bool, str]:
    if not _XDOTOOL:
        return False, "xdotool не установлен"
    return await _run_capture(f"{shlex.quote(_XDOTOOL)} {args}", timeout=timeout)


async def _ydotool(args: str, *, timeout: int = 20) -> tuple[bool, str]:
    """Fallback input via kernel uinput (root)."""
    if not shutil.which("ydotool"):
        return False, "ydotool не установлен"
    return await _run_capture(f"ydotool {args}", sudo=True, timeout=timeout)


async def _mouse_move(x: int, y: int) -> tuple[bool, str]:
    ok, info = await _xdotool(f"mousemove --sync {int(x)} {int(y)}")
    if ok:
        return ok, info
    # fallback: relative hack
    return await _ydotool(f"mousemove -- -30000 -30000 && ydotool mousemove -- {int(x)} {int(y)}")


async def _click_at(
    x: int | None, y: int | None, button: int = 1, double: bool = False,
) -> tuple[bool, str]:
    # xdotool buttons: 1=left, 2=middle, 3=right
    xbtn = {1: "1", 2: "2", 3: "3"}.get(button, str(button))
    prefix = f"mousemove --sync {int(x)} {int(y)} " if x is not None and y is not None else ""
    if double:
        ok, info = await _xdotool(f"{prefix}click --repeat 2 {xbtn}")
    else:
        ok, info = await _xdotool(f"{prefix}click {xbtn}")
    if ok:
        return ok, info
    # ydotool fallback
    ybtn = {1: "1", 2: "3", 3: "2"}.get(button, "1")
    seq = ""
    if x is not None and y is not None:
        seq = f"mousemove -- -30000 -30000 && ydotool mousemove -- {int(x)} {int(y)} && ydotool "
    clicks = f"click {ybtn}" + (" && ydotool click " + ybtn if double else "")
    return await _ydotool(f"{seq}{clicks}")


async def _type_text(text: str) -> tuple[bool, str]:
    ok, info = await _xdotool(f"type --delay 12 {shlex.quote(text)}")
    if ok:
        return ok, info
    return await _ydotool(f"type -- {shlex.quote(text)}")


async def _key_press(keys: str) -> tuple[bool, str]:
    ok, info = await _xdotool(f"key -- {keys}")
    if ok:
        return ok, info
    return await _ydotool(f"key {shlex.quote(keys)}")


# ─── Application discovery (no hardcoded list) ────────────────────────────────
_APP_DIRS = [
    "/usr/share/applications",
    "/usr/local/share/applications",
    str(Path.home() / ".local/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    str(Path.home() / ".local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
]
_APP_CACHE: list[dict] = []
_APP_CACHE_AT: float = 0.0


def _discover_apps() -> list[dict]:
    """Scan .desktop files → [{name, id, exec, keywords}]. Cached 60s."""
    global _APP_CACHE, _APP_CACHE_AT
    if _APP_CACHE and (time.time() - _APP_CACHE_AT) < 60:
        return _APP_CACHE
    apps: dict[str, dict] = {}
    for d in _APP_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in p.glob("*.desktop"):
            try:
                txt = f.read_text("utf-8", "replace")
            except Exception:
                continue
            if "NoDisplay=true" in txt and "Type=Application" not in txt:
                continue
            name = _ini_get(txt, "Name")
            exec_line = _ini_get(txt, "Exec")
            keywords = " ".join(filter(None, [
                _ini_get(txt, "GenericName"), _ini_get(txt, "Keywords"),
                _ini_get(txt, "Comment"),
            ]))
            app_id = f.stem
            if not name:
                name = app_id
            apps[app_id] = {"name": name, "id": app_id,
                            "exec": exec_line, "keywords": keywords}
    _APP_CACHE = list(apps.values())
    _APP_CACHE_AT = time.time()
    return _APP_CACHE


def _ini_get(txt: str, key: str) -> str:
    m = re.search(rf"^{re.escape(key)}=(.+)$", txt, re.MULTILINE)
    return (m.group(1).strip() if m else "")


def _match_app(query: str) -> dict | None:
    q = query.lower().strip()
    if not q:
        return None
    apps = _discover_apps()
    best, best_score = None, 0
    for a in apps:
        hay = f"{a['name']} {a['id']} {a['keywords']}".lower()
        score = 0
        if q == a["name"].lower() or q == a["id"].lower():
            score = 100
        elif q in a["name"].lower():
            score = 80 - abs(len(a["name"]) - len(q))
        elif q in hay:
            score = 50
        else:
            # token overlap
            qt = set(q.split())
            ht = set(hay.split())
            if qt & ht:
                score = 30 + len(qt & ht)
        if score > best_score:
            best, best_score = a, score
    return best if best_score >= 30 else None


# ─── Chromium/Chrome profiles (direct launch, no profile picker) ──────────────
_CHROMIUM_BINARIES = ("chromium", "chromium-browser",
                      "google-chrome", "google-chrome-stable", "/snap/bin/chromium")


def _chromium_binary() -> str | None:
    for b in _CHROMIUM_BINARIES:
        if Path(b).is_file():
            return b
        found = shutil.which(b)
        if found:
            return found
    return None


def _chrome_profile_bases() -> list[Path]:
    home = Path.home()
    return [
        home / "snap/chromium/common/chromium",
        home / ".config/chromium",
        home / ".config/google-chrome",
    ]


def _list_chrome_profiles() -> list[dict]:
    profiles: list[dict] = []
    seen: set[str] = set()
    for base in _chrome_profile_bases():
        ls = base / "Local State"
        if not ls.is_file():
            continue
        try:
            data = json.loads(ls.read_text("utf-8"))
        except Exception:
            continue
        for dir_id, info in data.get("profile", {}).get("info_cache", {}).items():
            name = info.get("name") or dir_id
            key = f"{name}:{dir_id}"
            if key in seen:
                continue
            seen.add(key)
            profiles.append(
                {"name": name, "directory": dir_id, "base": str(base)})
    return profiles


def _match_chrome_profile(query: str) -> dict | None:
    q = query.lower().strip()
    if not q:
        return None
    profiles = _list_chrome_profiles()
    best, best_score = None, 0
    for p in profiles:
        name = p["name"].lower()
        score = 0
        if name == q:
            score = 100
        elif q in name or name in q:
            score = 80
        elif q in name.split():
            score = 70
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 70 else None


# CLI binary aliases — terminal names for fuzzy queries (NOT web URLs)
_CLI_ALIASES: dict[str, list[str]] = {
    "хром": ["chromium", "google-chrome-stable", "google-chrome"],
    "chrome": ["chromium", "google-chrome-stable", "google-chrome"],
    "chromium": ["chromium"],
    "firefox": ["firefox"],
    "браузер": ["firefox", "chromium"],
    "код": ["cursor", "code", "codium"],
    "vscode": ["cursor", "code"],
    "vs code": ["cursor", "code"],
    "cursor": ["cursor"],
    "курсор": ["cursor"],
    "телеграм": ["telegram-desktop"],
    "telegram": ["telegram-desktop"],
    "терминал": ["gnome-terminal", "konsole"],
    "файлы": ["nautilus", "thunar"],
    "музыка": ["rhythmbox"],
    "rhythmbox": ["rhythmbox"],
    "редактор": ["gnome-text-editor", "gedit"],
    "текстовый редактор": ["gnome-text-editor", "gedit"],
    "text editor": ["gnome-text-editor", "gedit"],
}


def _cli_binaries_for(query: str) -> list[str]:
    q = query.lower().strip()
    out: list[str] = []
    for alias, bins in _CLI_ALIASES.items():
        if alias in q or q == alias:
            out.extend(bins)
    parts = q.split()
    if parts:
        out.append(parts[0])
    seen: set[str] = set()
    result: list[str] = []
    for b in out:
        if b and b not in seen:
            seen.add(b)
            result.append(b)
    return result


async def _run_cli(cmd: str) -> tuple[bool, str]:
    """Run shell command detached in GUI session."""
    wrapped = cmd if cmd.rstrip().endswith(
        "&") else f"nohup {cmd} >/dev/null 2>&1 &"
    return await _run_capture(wrapped, timeout=15)


def _pgrep_pattern_for(query: str, app: dict | None = None) -> str:
    """Best-effort pgrep -f pattern for verifying a GUI app launch."""
    if app and app.get("exec"):
        exe = re.sub(r"%[fFuUdDnNickvm]", "", app["exec"]).strip()
        if exe:
            token = Path(exe.split()[0]).name
            if token and token not in ("env", "sh", "bash"):
                return token
    bins = _cli_binaries_for(query)
    if bins:
        return bins[0]
    return query.strip().split()[0] if query.strip() else query


async def _pgrep_pids(pattern: str) -> set[int]:
    if not pattern:
        return set()
    ok, out = await _run_capture(
        f"pgrep -f {shlex.quote(pattern)} 2>/dev/null || true", timeout=8,
    )
    pids: set[int] = set()
    if ok:
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
    return pids


async def _verify_process(pattern: str, *, before: set[int] | None = None, timeout: float = 4.0) -> tuple[bool, str]:
    """Wait until process appears (new PID or any match). Returns (ok, detail)."""
    if not pattern:
        return False, "нет паттерна процесса"
    deadline = time.time() + timeout
    while time.time() < deadline:
        after = await _pgrep_pids(pattern)
        if before is not None and after - before:
            pid = next(iter(after - before))
            return True, f"новый процесс pid={pid}"
        if after:
            return True, f"процесс есть (pids={len(after)})"
        await asyncio.sleep(0.45)
    return False, f"процесс «{pattern}» не появился за {timeout:.0f}с"


async def _list_running_gui_apps() -> list[str]:
    """Running GUI apps via pgrep (works on Wayland)."""
    found: list[str] = []
    for label, pat in _GUI_PROC_PATTERNS:
        pids = await _pgrep_pids(pat)
        if pids:
            found.append(f"{label} ({len(pids)} proc)")
    return found


async def _title_bar_hint() -> str:
    """OCR top of screen → approximate active window title (Wayland fallback)."""
    size, elements, path = await _ocr_scan(fast=True)
    if path:
        try:
            path.unlink()
        except Exception:
            pass
    if not elements:
        return ""
    top = sorted([e for e in elements if e["top"] < 90],
                 key=lambda e: (e["top"], e["left"]))
    if not top:
        return ""
    return " ".join(e["text"] for e in top[:10]).strip()


async def _get_window_context(*, ocr: bool = True) -> str:
    """Where am I: running apps + wmctrl + OCR title bar."""
    parts: list[str] = []

    running = await _list_running_gui_apps()
    if running:
        parts.append("Запущено: " + ", ".join(running))

    if shutil.which("wmctrl"):
        ok, out = await _run_capture("wmctrl -l", timeout=5)
        if ok and out and out not in ("(пусто)", ""):
            lines = [l.strip() for l in out.splitlines() if l.strip()][:8]
            if lines:
                parts.append("Окна (wmctrl):\n" + "\n".join(lines))

    if ocr:
        hint = await _title_bar_hint()
        if hint:
            parts.append(f"Видно на экране (OCR верх): «{hint}»")

    if not parts:
        return "Контекст окна неизвестен (Wayland). Используй read_screen или screenshot."
    return "\n".join(parts)


async def _activate_app(app: dict | None, query: str) -> None:
    """Try to bring app to front (gtk-launch re-fire works on GNOME for many apps)."""
    if app and shutil.which("gtk-launch"):
        await _spawn(["gtk-launch", app["id"]])
        await asyncio.sleep(0.6)
        return
    for title in (app["name"] if app else "", query, query.title()):
        if title:
            await _focus_window(title)
            await asyncio.sleep(0.25)


async def _launch_and_verify(
    query: str,
    launch_fn,
    *,
    app: dict | None = None,
    label: str = "",
) -> ToolResult:
    """Launch via callback, verify process, activate, return honest result + context."""
    pattern = _pgrep_pattern_for(query, app)
    before = await _pgrep_pids(pattern)
    ok, info = await launch_fn()
    if not ok:
        ctx = await _get_window_context(ocr=False)
        return ToolResult(
            success=False, output="",
            error=f"Не удалось запустить «{label or query}»: {info}\n{ctx}",
        )

    verified, detail = await _verify_process(pattern, before=before, timeout=4.5)
    await _activate_app(app, query)
    ctx = await _get_window_context(ocr=True)

    name = label or (app["name"] if app else query)
    if verified:
        return ToolResult(
            success=True,
            output=(f"✅ «{name}» — процесс подтверждён ({detail}).\n{ctx}"),
        )
    return ToolResult(
        success=False, output="",
        error=(
            f"Команда отправлена, но «{name}» не подтверждён ({detail}). "
            f"Возможно окно не появилось на экране.\n{ctx}"
        ),
    )


async def _focus_window(title: str) -> None:
    if not title or not shutil.which("wmctrl"):
        return
    await _run_capture(f"wmctrl -a {shlex.quote(title)}", timeout=5)
    await asyncio.sleep(0.35)


async def _open_chrome_profile(name: str) -> ToolResult:
    """Launch Chromium/Chrome directly into a named profile (skips picker screen)."""
    binary = _chromium_binary()
    if not binary:
        return ToolResult(success=False, output="", error="Chromium/Chrome не установлен")
    profile = _match_chrome_profile(name)
    if not profile:
        names = ", ".join(p["name"]
                          for p in _list_chrome_profiles()) or "(нет)"
        return ToolResult(
            success=False, output="",
            error=(f"CLI: профиль «{name}» не найден. Есть: {names}. "
                   f"Попробуй desktop(run) с --profile-directory. "
                   f"click_text — только если CLI не сработал."),
        )

    cmd = f"{shlex.quote(binary)} --profile-directory={shlex.quote(profile['directory'])}"
    label = f"Chrome «{profile['name']}»"

    async def _do_launch() -> tuple[bool, str]:
        ok, info = await _run_cli(cmd)
        if ok:
            return True, cmd
        ok2, info2 = await _spawn([binary, f"--profile-directory={profile['directory']}"])
        return ok2, info2 or info

    return await _launch_and_verify(
        "chromium", _do_launch, label=label,
    )


async def _open_app(query: str) -> ToolResult:
    """Open app via TERMINAL (gtk-launch / binary / snap). Verify process before claiming success."""
    q = query.strip()
    if not q:
        return ToolResult(success=False, output="", error="Пустое имя приложения")

    app = _match_app(q)

    async def _try_gtk() -> tuple[bool, str]:
        if app and shutil.which("gtk-launch"):
            return await _spawn(["gtk-launch", app["id"]])
        return False, "gtk-launch недоступен"

    async def _try_exec() -> tuple[bool, str]:
        if app:
            exec_clean = re.sub(r"%[fFuUdDnNickvm]", "",
                                app.get("exec", "")).strip()
            if exec_clean:
                return await _run_cli(exec_clean)
        return False, "нет Exec в .desktop"

    async def _try_bins() -> tuple[bool, str]:
        for bin_name in _cli_binaries_for(q):
            path = shutil.which(bin_name)
            if path:
                ok, info = await _run_cli(shlex.quote(path))
                if ok:
                    return True, path
        if shutil.which("snap"):
            for cand in _cli_binaries_for(q):
                ok, info = await _run_cli(f"snap run {shlex.quote(cand)}")
                if ok:
                    return True, f"snap run {cand}"
        return False, "бинарь не найден"

    async def _try_path() -> tuple[bool, str]:
        p = Path(q).expanduser()
        if p.exists():
            return await _spawn(["xdg-open", str(p)])
        return False, "путь не существует"

    for launcher in (_try_gtk, _try_exec, _try_bins, _try_path):
        result = await _launch_and_verify(
            q, launcher, app=app, label=app["name"] if app else q,
        )
        if result.success:
            return result
        # Only continue if launch command itself failed, not verify — actually _launch_and_verify
        # returns failure for verify too. Try next launcher only when launch failed.
        if "Не удалось запустить" in (result.error or ""):
            continue
        return result  # verify failed after a launcher ran — don't lie with another attempt

    ctx = await _get_window_context(ocr=False)
    return ToolResult(
        success=False, output="",
        error=(
            f"CLI: не открыл «{q}». Используй desktop(run, «команда») или list_apps.\n{ctx}"),
    )


def _resolve_note_path(path: str = "") -> Path:
    """Writable note path under user_files (or explicit path)."""
    if path.strip():
        p = Path(path.strip()).expanduser()
        if not p.is_absolute():
            p = USER_FILES_DIR / p
    else:
        p = USER_FILES_DIR / f"note_{int(time.time())}.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def _edit_text(content: str, path: str = "") -> ToolResult:
    """Write text to disk, verify on disk, open in GUI text editor, verify process."""
    text = (content or "").strip()
    if not text:
        return ToolResult(success=False, output="", error="Пустой текст — нечего записывать")

    p = _resolve_note_path(path)
    try:
        p.write_text(text, encoding="utf-8")
        on_disk = p.read_text(encoding="utf-8")
    except Exception as exc:
        return ToolResult(success=False, output="", error=f"Ошибка записи файла: {exc}")

    if on_disk.strip() != text.strip():
        return ToolResult(
            success=False, output="",
            error="Запись на диск не совпала с текстом — файл не открываю.",
        )

    editor_bin = shutil.which("gnome-text-editor") or shutil.which("gedit")

    async def _launch_editor() -> tuple[bool, str]:
        if editor_bin:
            return await _run_cli(f"{shlex.quote(editor_bin)} {shlex.quote(str(p))}")
        return await _spawn(["xdg-open", str(p)])

    pattern = "gnome-text-editor" if editor_bin else "xdg-open"
    result = await _launch_and_verify(
        pattern, _launch_editor, label=f"Текстовый редактор ({p.name})",
    )

    preview = text if len(text) <= 400 else text[:400] + "…"
    if not result.success:
        return ToolResult(
            success=False, output="",
            error=(
                f"Текст записан в {p} и проверен на диске, но редактор не открылся.\n"
                f"{result.error or ''}\nСодержимое: «{preview}»"
            ),
            artifacts=[{"type": "file", "path": str(
                p), "caption": "Записанный текст"}],
        )

    return ToolResult(
        success=True,
        output=(
            f"✅ Записано в {p} (проверено на диске) и открыто в редакторе.\n"
            f"Текст: «{preview}»\n{result.output}"
        ),
        artifacts=[{"type": "file", "path": str(
            p), "caption": "Записанный текст"}],
    )


# ─── Vision: screenshot + OCR ─────────────────────────────────────────────────
def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as f:
            head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
    except Exception:
        pass
    return None


async def _capture(path: Path) -> bool:
    backends = []
    if shutil.which("gnome-screenshot"):
        backends.append(["gnome-screenshot", "-f", str(path)])
    if shutil.which("scrot"):
        backends.append(["scrot", "-o", str(path)])
    if shutil.which("import"):
        backends.append(f"import -window root {path}")
    for cmd in backends:
        try:
            if isinstance(cmd, list):
                proc = await asyncio.create_subprocess_exec(
                    *cmd, env=_gui_env(),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            else:
                proc = await asyncio.create_subprocess_shell(
                    cmd, env=_gui_env(),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(proc.wait(), timeout=15)
        except Exception:
            continue
        if path.exists() and path.stat().st_size > 0:
            return True
    return False


async def _screenshot() -> ToolResult:
    path = USER_FILES_DIR / f"desktop_{int(time.time())}.png"
    if not await _capture(path):
        return ToolResult(success=False, output="", error="Не удалось снять скриншот экрана.")
    size = _png_size(path)
    dim = f" ({size[0]}x{size[1]})" if size else ""
    return ToolResult(
        success=True, output=f"Скриншот экрана{dim} прикреплён к ответу.",
        artifacts=[{"type": "file", "path": str(
            path), "caption": "Скриншот экрана"}],
    )


def _norm_text(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def _parse_ocr_tsv(raw: str) -> list[dict]:
    """Parse tesseract TSV → [{text, x, y, left, top, w, h, conf}]."""
    elements: list[dict] = []
    for line in raw.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        text = cols[11].strip()
        if conf < 35 or not text or len(text) < 1:
            continue
        # Skip pure symbols/noise ($, &, etc.)
        if not re.search(r"[a-zA-Zа-яА-ЯёЁ0-9]", text):
            continue
        left, top, w, h = int(cols[6]), int(
            cols[7]), int(cols[8]), int(cols[9])
        elements.append({
            "text": text, "conf": conf,
            "left": left, "top": top, "w": w, "h": h,
            "x": left + w // 2, "y": top + h // 2,
        })
    return elements


def _group_ocr_lines(elements: list[dict]) -> list[dict]:
    """Merge words on the same visual line into phrases (better for 'Work', profile names)."""
    if not elements:
        return []
    sorted_el = sorted(elements, key=lambda e: (e["top"], e["left"]))
    lines: list[list[dict]] = []
    for el in sorted_el:
        placed = False
        for group in lines:
            ref = group[0]
            if abs(el["top"] - ref["top"]) <= max(18, ref["h"]):
                group.append(el)
                placed = True
                break
        if not placed:
            lines.append([el])
    phrases: list[dict] = []
    for group in lines:
        group.sort(key=lambda e: e["left"])
        text = " ".join(e["text"] for e in group)
        left = min(e["left"] for e in group)
        top = min(e["top"] for e in group)
        right = max(e["left"] + e["w"] for e in group)
        bottom = max(e["top"] + e["h"] for e in group)
        phrases.append({
            "text": text, "conf": sum(e["conf"] for e in group) / len(group),
            "left": left, "top": top, "w": right - left, "h": bottom - top,
            "x": (left + right) // 2, "y": (top + bottom) // 2,
        })
    return phrases


def _match_ocr(elements: list[dict], query: str) -> list[dict]:
    """Find OCR hits for query — words, phrases, fuzzy."""
    q = _norm_text(query)
    if not q:
        return []
    phrases = _group_ocr_lines(elements) + elements
    scored: list[tuple[float, dict]] = []
    seen: set[str] = set()
    for el in phrases:
        raw = el["text"]
        norm = _norm_text(raw)
        if not norm or norm in seen:
            continue
        score = 0.0
        if norm == q:
            score = 100.0
        elif q in norm:
            score = 80.0 - abs(len(norm) - len(q)) * 0.5
        elif norm in q:
            # Reject spurious substring hits: "on" inside "songs", "x" inside "mix"
            if len(norm) < 3 or (len(norm) < len(q) * 0.55 and len(norm) <= 3):
                score = 0.0
            else:
                score = 70.0
        else:
            qt = set(q.split())
            nt = set(norm.split())
            overlap = len(qt & nt)
            if overlap:
                score = 40.0 + overlap * 15
        if score >= 40:
            seen.add(norm)
            # Boost exact short names (e.g. profile "Work" vs "work.ua")
            if norm == q and len(norm) <= 12:
                score += 25
            scored.append((score + el["conf"] * 0.05, el))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [el for _, el in scored]


async def _ocr_scan(*, fast: bool = False) -> tuple[tuple[int, int], list[dict], Path | None]:
    """Capture screen + OCR. Returns (screen_size, elements, screenshot_path). Cached 2s."""
    global _OCR_CACHE_AT, _OCR_CACHE_DATA
    if not shutil.which("tesseract"):
        return (0, 0), [], None
    now = time.time()
    if not fast and _OCR_CACHE_DATA and (now - _OCR_CACHE_AT) < 2.0:
        return _OCR_CACHE_DATA

    path = USER_FILES_DIR / f"ocr_{int(now)}.png"
    if not await _capture(path):
        return (0, 0), [], None
    size = _png_size(path) or (0, 0)
    psm = "6" if fast else "11"  # psm 6 = faster uniform block layout
    ok, out = await _run_capture(
        f"tesseract {shlex.quote(str(path))} stdout -l rus+eng --psm {psm} tsv", timeout=30)
    if not ok:
        return size, [], path
    elements = _parse_ocr_tsv(out)
    _OCR_CACHE_AT = now
    _OCR_CACHE_DATA = (size, elements, None)
    return size, elements, path


_OCR_CACHE_AT: float = 0.0
_OCR_CACHE_DATA: tuple[tuple[int, int], list[dict], Path | None] | None = None


async def _click_text(query: str) -> ToolResult:
    """Find text on screen via OCR and click it — one-shot, reliable."""
    if not query.strip():
        return ToolResult(success=False, output="", error="укажи текст для клика (target)")
    # Focus browser window so OCR sees the profile picker, not Telegram behind it
    for title in ("Chromium", "Chrome", "Google Chrome", "Firefox"):
        await _focus_window(title)
    size, elements, path = await _ocr_scan(fast=True)
    if not elements:
        err = "OCR не нашёл текст на экране"
        if path and path.exists():
            err += " (экран пуст или tesseract недоступен)"
        return ToolResult(success=False, output="", error=err)
    hits = _match_ocr(elements, query)
    if not hits:
        visible = ", ".join(sorted({e["text"] for e in elements})[:40])
        return ToolResult(
            success=False, output="",
            error=(f"Текст «{query}» не найден на экране {size[0]}x{size[1]}. "
                   f"Видно: {visible}"),
        )
    best = hits[0]
    x, y = best["x"], best["y"]
    # nudge click slightly below center for profile cards / buttons
    y_click = min(y + best["h"] // 4, (size[1] or 1080) - 1)
    logger.info(f"click_text «{query}» → «{best['text']}» @ {x},{y_click}")
    ok, info = await _click_at(x, y_click, button=1)
    await asyncio.sleep(0.4)
    if path:
        try:
            path.unlink()
        except Exception:
            pass
    if not ok:
        return ToolResult(success=False, output="", error=f"Клик не удался: {info}")
    return ToolResult(
        success=True,
        output=(f"Кликнул по «{best['text']}» @ {x},{y_click} "
                f"(искал: «{query}», экран {size[0]}x{size[1]})"),
    )


async def _play_music() -> ToolResult:
    """Open local music player and start playback."""
    # 1) Try Rhythmbox (installed on this system)
    rb = _match_app("rhythmbox") or _match_app("Rhythmbox")
    if rb and shutil.which("gtk-launch"):
        await _spawn(["gtk-launch", rb["id"]])
        await asyncio.sleep(1.5)
    elif shutil.which("rhythmbox"):
        await _spawn("rhythmbox")
        await asyncio.sleep(1.5)
    # 2) Start playback
    if shutil.which("rhythmbox-client"):
        ok, info = await _run_capture("rhythmbox-client --play", timeout=10)
        if ok:
            return ToolResult(success=True, output="Rhythmbox открыт, воспроизведение запущено")
    if shutil.which("playerctl"):
        ok, _ = await _run_capture("playerctl play", timeout=10)
        if ok:
            return ToolResult(success=True, output="Воспроизведение запущено (playerctl)")
    return ToolResult(
        success=False, output="",
        error="Не удалось запустить музыку. Попробуй open_app «Rhythmbox» или уточни приложение.",
    )


async def _read_screen(query: str = "") -> ToolResult:
    """OCR the whole screen → text + clickable elements with coordinates."""
    size, elements, path = await _ocr_scan()
    if path:
        try:
            path.unlink()
        except Exception:
            pass
    if not elements:
        return ToolResult(success=False, output="", error="OCR не нашёл текст на экране")
    if query:
        hits = _match_ocr(elements, query)
        if not hits:
            visible = ", ".join(sorted({e["text"] for e in elements})[:30])
            return ToolResult(
                success=True,
                output=(f"Текст «{query}» на экране не найден. "
                        f"Видно ({len(elements)} слов): {visible}"),
            )
        lines = [f'«{h["text"]}» @ {h["x"]},{h["y"]}' for h in hits[:15]]
        return ToolResult(success=True, output="Найдено на экране:\n" + "\n".join(lines))
    phrases = _group_ocr_lines(elements)
    words = " ".join(p["text"] for p in phrases[:60])
    coords = "\n".join(
        f'«{p["text"]}» @ {p["x"]},{p["y"]}' for p in phrases[:80])
    return ToolResult(
        success=True,
        output=(f"ЭКРАН {size[0]}x{size[1]} (OCR). Текст:\n{words[:2000]}\n\n"
                f"ЭЛЕМЕНТЫ (текст @ x,y):\n{coords}"),
    )


# ─── Media / volume / clipboard ───────────────────────────────────────────────
async def _volume(target: str) -> ToolResult:
    t = target.lower().strip()
    sink = "@DEFAULT_SINK@"
    if shutil.which("pactl"):
        cmd = {
            "mute": f"pactl set-sink-mute {sink} toggle",
            "up": f"pactl set-sink-volume {sink} +10%", "volup": f"pactl set-sink-volume {sink} +10%",
            "down": f"pactl set-sink-volume {sink} -10%", "voldown": f"pactl set-sink-volume {sink} -10%",
        }.get(t)
        if not cmd and t.isdigit():
            cmd = f"pactl set-sink-volume {sink} {t}%"
    else:
        ctl = "amixer -D pulse" if shutil.which("amixer") else None
        if not ctl:
            return ToolResult(success=False, output="", error="нет pactl/amixer")
        cmd = {
            "mute": f"{ctl} set Master toggle",
            "up": f"{ctl} set Master 10%+", "volup": f"{ctl} set Master 10%+",
            "down": f"{ctl} set Master 10%-", "voldown": f"{ctl} set Master 10%-",
        }.get(t)
        if not cmd and t.isdigit():
            cmd = f"{ctl} set Master {t}%"
    if not cmd:
        return ToolResult(success=False, output="", error=f"volume: {target}? (up/down/mute/0-100)")
    ok, info = await _run_capture(cmd, timeout=10)
    return ToolResult(success=ok, output=f"Громкость: {target}" if ok else "", error="" if ok else info)


async def _media(target: str) -> ToolResult:
    t = target.lower().strip()
    mapping = {"play": "play", "pause": "pause", "toggle": "play-pause", "playpause": "play-pause",
               "next": "next", "prev": "previous", "previous": "previous", "stop": "stop"}
    if shutil.which("playerctl") and t in mapping:
        ok, _ = await _run_capture(f"playerctl {mapping[t]}", timeout=10)
        if ok:
            return ToolResult(success=True, output=f"Медиа: {target}")
    keymap = {"play": "XF86AudioPlay", "pause": "XF86AudioPause", "toggle": "XF86AudioPlay",
              "next": "XF86AudioNext", "prev": "XF86AudioPrev", "previous": "XF86AudioPrev",
              "stop": "XF86AudioStop"}
    if t in keymap and shutil.which("xdotool"):
        ok, info = await _spawn(["xdotool", "key", keymap[t]])
        return ToolResult(success=ok, output=f"Медиа: {target}" if ok else "", error="" if ok else info)
    return ToolResult(success=False, output="", error=f"Не удалось выполнить медиа-действие: {target}")


async def _clipboard(set_text: str | None) -> ToolResult:
    if set_text is not None:
        if shutil.which("wl-copy"):
            ok, info = await _spawn(f"printf %s {shlex.quote(set_text)} | wl-copy")
        elif shutil.which("xclip"):
            ok, info = await _spawn(f"printf %s {shlex.quote(set_text)} | xclip -selection clipboard")
        else:
            return ToolResult(success=False, output="", error="нет wl-copy/xclip")
        return ToolResult(success=ok, output="Скопировано в буфер" if ok else "", error="" if ok else info)
    if shutil.which("wl-paste"):
        ok, info = await _run_capture("wl-paste -n", timeout=10)
    elif shutil.which("xclip"):
        ok, info = await _run_capture("xclip -selection clipboard -o", timeout=10)
    else:
        return ToolResult(success=False, output="", error="нет wl-paste/xclip")
    return ToolResult(success=ok, output=info, error="" if ok else info)


# ─── Main dispatcher ──────────────────────────────────────────────────────────
async def _desktop(
    action: str,
    target: str = "",
    x: int | None = None,
    y: int | None = None,
    content: str = "",
) -> ToolResult:
    action = (action or "").lower().strip()
    try:
        # discovery & launch
        if action == "list_apps":
            apps = _discover_apps()
            names = sorted({a["name"] for a in apps})
            return ToolResult(success=True,
                              output=f"Установлено приложений: {len(names)}\n" + ", ".join(names[:200]))
        if action in ("chrome_profiles", "list_chrome_profiles"):
            profiles = _list_chrome_profiles()
            if not profiles:
                return ToolResult(success=False, output="", error="Профили Chrome/Chromium не найдены")
            lines = [
                f"• «{p['name']}» (directory={p['directory']})" for p in profiles]
            return ToolResult(success=True, output="Профили Chrome/Chromium:\n" + "\n".join(lines))
        if action in ("chrome_profile", "open_chrome_profile", "browser_profile"):
            return await _open_chrome_profile(target)
        if action in ("music", "play_music"):
            return await _play_music()
        if action in ("open_app", "app", "open", "launch"):
            return await _open_app(target)
        if action in ("edit_text", "write_and_open", "text_editor"):
            body = (content or target or "").strip()
            file_path = target.strip() if content and target and (
                "/" in target or target.endswith((".txt", ".md"))
            ) else ""
            return await _edit_text(body, path=file_path)
        if action in ("open_url", "url"):
            url = target if target.startswith(
                ("http://", "https://")) else "https://" + target
            ok, info = await _spawn(["xdg-open", url])
            return ToolResult(success=ok, output=f"Открыл {url}" if ok else "", error="" if ok else info)
        if action in ("spawn",):
            ok, info = await _spawn(target)
            return ToolResult(success=ok, output=info if ok else "", error="" if ok else info)
        if action in ("run", "exec", "cmd"):
            if not target:
                return ToolResult(success=False, output="", error="Пустая команда")
            ok, info = await _run_capture(target, timeout=120)
            return ToolResult(success=ok, output=info, error="" if ok else info)
        if action in ("sudo", "run_sudo"):
            if not target:
                return ToolResult(success=False, output="", error="Пустая команда")
            ok, info = await _run_capture(target, sudo=True, timeout=150)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        # vision
        if action == "screenshot":
            return await _screenshot()
        if action in ("read_screen", "ocr", "see"):
            return await _read_screen()
        if action in ("find", "locate", "find_on_screen"):
            return await _read_screen(target)
        if action in ("click_text", "click_on", "tap"):
            return await _click_text(target)

        # mouse
        if action in ("mouse_move", "move"):
            if x is None or y is None:
                return ToolResult(success=False, output="", error="нужны координаты x,y")
            ok, info = await _mouse_move(x, y)
            return ToolResult(success=ok, output=f"Курсор → {x},{y}" if ok else "", error="" if ok else info)
        if action in ("click", "left_click"):
            ok, info = await _click_at(x, y, button=1)
            return ToolResult(success=ok, output="Клик" + (f" @ {x},{y}" if x is not None else ""),
                              error="" if ok else info)
        if action in ("right_click",):
            ok, info = await _click_at(x, y, button=2)
            return ToolResult(success=ok, output="Правый клик", error="" if ok else info)
        if action in ("double_click", "dblclick"):
            ok, info = await _click_at(x, y, button=1, double=True)
            return ToolResult(success=ok, output="Двойной клик", error="" if ok else info)
        if action in ("scroll",):
            amount = int(x) if x else 3
            btn = "4" if "up" in target.lower() else "5"  # xdotool wheel buttons
            ok, info = await _xdotool(f"click --repeat {max(1, amount)} {btn}")
            if not ok:
                key = "Prior" if "up" in target.lower() else "Next"
                ok, info = await _key_press(" ".join([key] * max(1, amount)))
            return ToolResult(success=ok, output=f"Скролл {target or 'down'}", error="" if ok else info)
        if action in ("drag",):
            return ToolResult(success=False, output="",
                              error="drag: используй mouse_move к началу, затем click-hold (пока не поддержано низкоуровнево)")

        # keyboard
        if action == "type":
            if not target:
                return ToolResult(success=False, output="", error="нечего печатать")
            ok, info = await _type_text(target)
            return ToolResult(success=ok, output="Напечатано" if ok else "", error="" if ok else info)
        if action == "key":
            ok, info = await _key_press(target)
            return ToolResult(success=ok, output=f"Клавиши: {target}" if ok else "", error="" if ok else info)

        # media / volume / brightness / clipboard / notify
        if action == "media":
            return await _media(target)
        if action in ("volume", "vol"):
            return await _volume(target)
        if action == "brightness":
            if not shutil.which("brightnessctl"):
                return ToolResult(success=False, output="", error="brightnessctl не установлен")
            ok, info = await _run_capture(f"brightnessctl set {target.strip() or '50%'}", timeout=10)
            return ToolResult(success=ok, output=f"Яркость: {target}" if ok else "", error="" if ok else info)
        if action in ("clipboard_set", "copy"):
            return await _clipboard(target)
        if action in ("clipboard_get", "paste"):
            return await _clipboard(None)
        if action == "notify":
            if not shutil.which("notify-send"):
                return ToolResult(success=False, output="", error="notify-send не установлен")
            ok, info = await _spawn(["notify-send", "Итан", target or ""])
            return ToolResult(success=ok, output="Уведомление показано" if ok else "", error="" if ok else info)

        # windows / context
        if action in ("where_am_i", "context", "active_window", "where"):
            ctx = await _get_window_context(ocr=True)
            return ToolResult(success=True, output=ctx)
        if action in ("windows", "window_list"):
            ok, info = await _run_capture("wmctrl -l", timeout=10) if shutil.which("wmctrl") else (False, "wmctrl нет")
            return ToolResult(success=ok, output=info, error="" if ok else info)
        if action in ("focus", "activate"):
            ok, info = await _run_capture(f"wmctrl -a {shlex.quote(target)}", timeout=10) if shutil.which("wmctrl") else (False, "wmctrl нет")
            return ToolResult(success=ok, output=f"Окно: {target}" if ok else "", error="" if ok else info)
        if action == "close_window":
            ok, info = await _run_capture(f"wmctrl -c {shlex.quote(target)}", timeout=10) if shutil.which("wmctrl") else (False, "wmctrl нет")
            return ToolResult(success=ok, output=f"Закрыто: {target}" if ok else "", error="" if ok else info)

        # power
        if action == "power":
            t = target.lower().strip()
            cmds = {"lock": "loginctl lock-session", "suspend": "systemctl suspend",
                    "sleep": "systemctl suspend", "hibernate": "systemctl hibernate",
                    "shutdown": "systemctl poweroff", "poweroff": "systemctl poweroff",
                    "reboot": "systemctl reboot", "restart": "systemctl reboot",
                    "logout": "gnome-session-quit --logout --no-prompt"}
            cmd = cmds.get(t)
            if not cmd:
                return ToolResult(success=False, output="", error=f"power: {target}? (lock/suspend/shutdown/reboot/logout)")
            ok, info = await _run_capture(cmd, timeout=15)
            return ToolResult(success=ok, output=f"Питание: {target}" if ok else "", error="" if ok else info)

        # ── Full system control (sudo) ─────────────────────────────────────────
        if action in ("install", "install_package", "apt_install"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи название пакета для установки")
            pkg = shlex.quote(target.strip())
            ok, info = await _run_capture(
                f"apt-get install -y {pkg}", sudo=True, timeout=180)
            return ToolResult(success=ok, output=f"Установлено: {target}\n{info}" if ok else "",
                              error="" if ok else info)

        if action in ("remove", "uninstall", "uninstall_package", "apt_remove"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи название пакета для удаления")
            pkg = shlex.quote(target.strip())
            ok, info = await _run_capture(
                f"apt-get remove -y {pkg}", sudo=True, timeout=120)
            return ToolResult(success=ok, output=f"Удалено: {target}\n{info}" if ok else "",
                              error="" if ok else info)

        if action in ("update_system", "apt_update", "system_update"):
            ok, info = await _run_capture(
                "apt-get update && apt-get upgrade -y", sudo=True, timeout=300)
            return ToolResult(success=ok, output=f"Система обновлена:\n{info}" if ok else "",
                              error="" if ok else info)

        if action in ("service", "systemctl"):
            # target = "start nginx" or content = action, target = service name
            parts = target.strip().split(None, 1)
            if len(parts) == 2:
                svc_action, svc_name = parts[0], parts[1]
            elif len(parts) == 1 and content.strip():
                svc_action, svc_name = parts[0], content.strip()
            else:
                return ToolResult(success=False, output="",
                                  error="service: укажи target='<start|stop|restart|status|enable|disable> <service>'")
            allowed = {"start", "stop", "restart", "status", "enable", "disable",
                       "reload", "is-active", "is-enabled", "list-units"}
            if svc_action not in allowed:
                return ToolResult(success=False, output="",
                                  error=f"service: недопустимое действие «{svc_action}». Доступно: {', '.join(sorted(allowed))}")
            use_sudo = svc_action not in (
                "status", "is-active", "is-enabled", "list-units")
            cmd = f"systemctl {shlex.quote(svc_action)} {shlex.quote(svc_name)}"
            ok, info = await _run_capture(cmd, sudo=use_sudo, timeout=30)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("list_services",):
            ok, info = await _run_capture(
                "systemctl list-units --type=service --state=running --no-pager --plain 2>&1 | head -60",
                timeout=15)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("kill_process", "pkill", "kill"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи имя процесса или PID")
            t = target.strip()
            if t.isdigit():
                ok, info = await _run_capture(f"kill -9 {t}", sudo=True, timeout=10)
                return ToolResult(success=ok, output=f"Процесс {t} завершён" if ok else "",
                                  error="" if ok else info)
            ok, info = await _run_capture(f"pkill -f {shlex.quote(t)}", timeout=10)
            if not ok:
                ok, info = await _run_capture(f"pkill -f {shlex.quote(t)}", sudo=True, timeout=10)
            return ToolResult(success=ok, output=f"Завершены процессы: {t}\n{info}" if ok else "",
                              error="" if ok else info)

        if action in ("processes", "ps", "process_list"):
            q = target.strip()
            if q:
                ok, info = await _run_capture(
                    f"ps aux | grep -i {shlex.quote(q)} | grep -v grep | head -20", timeout=10)
            else:
                ok, info = await _run_capture(
                    "ps aux --sort=-%cpu | head -25", timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("system_info", "sysinfo", "info"):
            ok, info = await _run_capture(
                "echo '=== ОС ===' && uname -a && echo '=== АПТАЙМ ===' && uptime -p && "
                "echo '=== ПАМЯТЬ ===' && free -h && echo '=== ДИСК ===' && df -h --total | tail -6 && "
                "echo '=== CPU ===' && lscpu | grep -E 'Model name|CPU\\(s\\)|MHz'",
                timeout=20)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("disk", "disk_info", "df"):
            ok, info = await _run_capture("df -h", timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("network", "net", "network_info"):
            t = target.lower().strip()
            if t in ("status", "") or not t:
                ok, info = await _run_capture(
                    "echo '=== IP ===' && ip -brief addr show && "
                    "echo '=== WiFi ===' && nmcli -f DEVICE,STATE,CONNECTION dev status 2>/dev/null || true",
                    timeout=15)
                return ToolResult(success=ok, output=info, error="" if ok else info)
            if t.startswith("connect "):
                ssid = t[len("connect "):].strip()
                ok, info = await _run_capture(
                    f"nmcli dev wifi connect {shlex.quote(ssid)}", sudo=True, timeout=30)
                return ToolResult(success=ok, output=f"Подключено к {ssid}" if ok else "",
                                  error="" if ok else info)
            if t == "disconnect":
                ok, info = await _run_capture("nmcli dev disconnect wlan0 2>/dev/null || nmcli dev disconnect wlo1",
                                              sudo=True, timeout=15)
                return ToolResult(success=ok, output="WiFi отключён" if ok else "", error="" if ok else info)
            if t.startswith("ping "):
                host = shlex.quote(t[5:].strip())
                ok, info = await _run_capture(f"ping -c 4 {host}", timeout=20)
                return ToolResult(success=ok, output=info, error="" if ok else info)
            ok, info = await _run_capture(f"nmcli {target}", timeout=20)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("firewall", "ufw"):
            t = target.strip()
            if not t or t == "status":
                ok, info = await _run_capture("ufw status verbose", sudo=True, timeout=10)
                return ToolResult(success=ok, output=info, error="" if ok else info)
            ok, info = await _run_capture(f"ufw {t}", sudo=True, timeout=15)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("user_add", "adduser"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи имя нового пользователя")
            ok, info = await _run_capture(f"adduser --disabled-password --gecos '' {shlex.quote(target.strip())}",
                                          sudo=True, timeout=30)
            return ToolResult(success=ok, output=f"Пользователь {target} создан:\n{info}" if ok else "",
                              error="" if ok else info)

        if action in ("chown", "chmod"):
            if not target.strip():
                return ToolResult(success=False, output="", error=f"{action}: укажи аргументы")
            ok, info = await _run_capture(f"{action} {target}", sudo=True, timeout=30)
            return ToolResult(success=ok, output=info if ok else "", error="" if ok else info)

        if action in ("env", "env_var", "set_env"):
            if not target.strip():
                ok, info = await _run_capture("env", timeout=10)
                return ToolResult(success=ok, output=info, error="" if ok else info)
            # target = "VAR=value"
            ok, info = await _run_capture(f"printenv {shlex.quote(target.strip())}", timeout=5)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("cron", "crontab"):
            t = target.strip()
            if t == "list" or not t:
                ok, info = await _run_capture("crontab -l 2>/dev/null || echo '(crontab пуст)'", timeout=10)
                return ToolResult(success=ok, output=info, error="" if ok else info)
            if t.startswith("add "):
                entry = t[4:].strip()
                ok, info = await _run_capture(
                    f"(crontab -l 2>/dev/null; echo {shlex.quote(entry)}) | crontab -", timeout=10)
                return ToolResult(success=ok, output=f"Задача добавлена в crontab: {entry}" if ok else "",
                                  error="" if ok else info)
            ok, info = await _run_capture(f"crontab {target}", timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("journal", "journalctl", "logs"):
            svc = shlex.quote(target.strip()) if target.strip() else ""
            cmd = f"journalctl -n 50 --no-pager {'-u ' + svc if svc else ''}"
            ok, info = await _run_capture(cmd, timeout=20)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("read_file", "cat_file"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи путь к файлу")
            p = Path(target.strip()).expanduser()
            # Try with sudo for protected files
            ok, info = await _run_capture(f"cat {shlex.quote(str(p))}", timeout=15)
            if not ok:
                ok, info = await _run_capture(f"cat {shlex.quote(str(p))}", sudo=True, timeout=15)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("write_file", "write_to_file"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи путь к файлу")
            if not content.strip():
                return ToolResult(success=False, output="", error="Укажи содержимое файла (content)")
            p = Path(target.strip()).expanduser()
            escaped = content.replace("'", "'\\''")
            ok, info = await _run_capture(
                f"printf '%s' '{escaped}' > {shlex.quote(str(p))}", sudo=True, timeout=30)
            return ToolResult(success=ok, output=f"Записано в {p}" if ok else "", error="" if ok else info)

        if action in ("run_as_root", "root_exec", "root"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи команду для root-выполнения")
            ok, info = await _run_capture(target.strip(), sudo=True, timeout=300)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("find_files", "locate_files"):
            query = target.strip()
            path_base = content.strip() or "/"
            ok, info = await _run_capture(
                f"find {shlex.quote(path_base)} -name {shlex.quote(query)} 2>/dev/null | head -50",
                timeout=30)
            return ToolResult(success=ok, output=info or "(не найдено)", error="" if ok else info)

        if action in ("which", "whereis"):
            if not target.strip():
                return ToolResult(success=False, output="", error="Укажи имя программы")
            ok, info = await _run_capture(f"which {shlex.quote(target.strip())} && whereis {shlex.quote(target.strip())}",
                                          timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("history", "bash_history"):
            ok, info = await _run_capture(
                "tail -100 ~/.bash_history 2>/dev/null || tail -100 ~/.zsh_history 2>/dev/null || echo '(история пуста)'",
                timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("user_info", "whoami", "id"):
            ok, info = await _run_capture("id && echo '---' && who && echo '---' && last -5", timeout=10)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        if action in ("port_scan", "netstat", "ports"):
            ok, info = await _run_capture(
                "ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null | head -40",
                sudo=True, timeout=15)
            return ToolResult(success=ok, output=info, error="" if ok else info)

        return ToolResult(success=False, output="", error=f"Неизвестное действие: {action}")
    except Exception as exc:
        logger.exception("desktop action failed")
        return ToolResult(success=False, output="", error=str(exc))


def register_desktop_tools() -> int:
    tool_registry.register(ToolSpec(
        name="desktop",
        description=(
            "Полное управление ПК владельца (Linux). Sudo пароль встроен. ПРИОРИТЕТ: ТЕРМИНАЛ, GUI — только если CLI не помог.\n"
            "БАЗОВЫЕ: open_app, edit_text, run/spawn (любая команда), sudo (sudo-команда), root_exec (как root), open_url,\n"
            "  chrome_profile «Work», music, volume/media, focus, where_am_i, power.\n"
            "ФАЙЛЫ: read_file «путь» — прочитать (в т.ч. системные с sudo); write_file «путь» (content=текст) — записать;\n"
            "  find_files «*.py» (content=«папка») — поиск файлов; which «программа».\n"
            "СИСТЕМНЫЕ (полный root-доступ):\n"
            "  install «пакет» — apt-get install;\n"
            "  remove «пакет» — apt-get remove;\n"
            "  update_system — apt update && upgrade;\n"
            "  service «start nginx» — systemd (start/stop/restart/status/enable/disable);\n"
            "  list_services — запущенные сервисы;\n"
            "  kill_process «имя/PID» — завершить процесс;\n"
            "  processes [«фильтр»] — список процессов;\n"
            "  system_info — ОС, RAM, диск, CPU;\n"
            "  disk — df -h;\n"
            "  network [status|connect <SSID>|disconnect|ping <host>] — сеть;\n"
            "  firewall [status|«ufw args»] — UFW;\n"
            "  ports — открытые порты (ss/netstat);\n"
            "  user_add «имя» — создать пользователя;\n"
            "  user_info — whoami, id, who, last;\n"
            "  chown/chmod «аргументы» — права файлов;\n"
            "  cron [list|add <entry>] — crontab;\n"
            "  journal [«сервис»] — journalctl логи;\n"
            "  history — история bash/zsh;\n"
            "  env [«VAR»] — переменные окружения.\n"
            "GUI (крайний случай): click_text, read_screen, click — только если CLI не сработал."
        ),
        parameters={"type": "object", "properties": {
            "action": {"type": "string", "enum": [
                "screenshot", "read_screen", "find", "click_text", "list_apps", "open_app",
                "edit_text", "write_and_open", "text_editor",
                "chrome_profiles", "chrome_profile", "music", "open_url", "spawn", "run", "sudo",
                "mouse_move", "click", "right_click", "double_click", "scroll", "type", "key",
                "media", "volume", "brightness", "clipboard_set", "clipboard_get", "notify",
                "where_am_i", "windows", "focus", "close_window", "power",
                # Full system access
                "install", "install_package", "apt_install",
                "remove", "uninstall", "uninstall_package", "apt_remove",
                "update_system", "apt_update",
                "service", "systemctl", "list_services",
                "kill_process", "pkill", "kill",
                "processes", "ps", "process_list",
                "system_info", "sysinfo", "info",
                "disk", "disk_info", "df",
                "network", "net", "network_info",
                "firewall", "ufw",
                "user_add", "adduser",
                "user_info", "whoami", "id",
                "chown", "chmod",
                "env", "env_var",
                "cron", "crontab",
                "journal", "journalctl", "logs",
                "history", "bash_history",
                "port_scan", "netstat", "ports",
                # File system full access
                "read_file", "cat_file",
                "write_file", "write_to_file",
                "run_as_root", "root_exec", "root",
                "find_files", "locate_files",
                "which", "whereis",
            ]},
            "target": {"type": "string", "description": (
                "Аргумент: имя пакета, путь к файлу, команда, имя процесса/сервиса, URL и т.д. "
                "Для service — «start nginx». Для write_file — путь к файлу. Для network — «connect MyWiFi»."
            )},
            "content": {"type": "string", "description": "Текст для write_file / edit_text; путь для find_files"},
            "x": {"type": "integer", "description": "X-координата мыши"},
            "y": {"type": "integer", "description": "Y-координата мыши"},
        }, "required": ["action"]},
        handler=_desktop, category="desktop", risk="high",
    ))
    return 1
