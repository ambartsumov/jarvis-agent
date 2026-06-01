"""
PDS-Ultimate Watchdog — автоматический перезапуск при падении.

Использование:
    python watchdog.py

Логика:
  - Запускает бота как subprocess
  - При любом падении (кроме Ctrl+C) — перезапускает
  - Экспоненциальный backoff: 3s → 6s → 12s → ... → max 60s
  - Сбрасывает backoff если бот проработал >5 минут стабильно
  - Пишет лог в pds_ultimate/logs/watchdog.log
"""

from __future__ import annotations

import subprocess
import sys
import time
import os
from datetime import datetime
from pathlib import Path

# ─── Настройки ───────────────────────────────────────────────────────────────

PYTHON = sys.executable                          # тот же интерпретатор
WORKDIR = Path(__file__).resolve().parent        # agent/
MODULE = "pds_ultimate.main"
LOG_FILE = WORKDIR / "pds_ultimate" / "logs" / "watchdog.log"

BACKOFF_INITIAL = 3       # начальная пауза между перезапусками (сек)
BACKOFF_MAX     = 60      # максимальная пауза
STABLE_UPTIME   = 300     # если работал >5 мин — сбрасываем backoff

# ─── Логирование ─────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | WATCHDOG | {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ─── Основной цикл ───────────────────────────────────────────────────────────

def run() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKDIR)

    backoff = BACKOFF_INITIAL
    attempt = 0

    _log("=" * 60)
    _log("PDS-Ultimate Watchdog запущен")
    _log(f"  Python   : {PYTHON}")
    _log(f"  Workdir  : {WORKDIR}")
    _log(f"  Backoff  : {BACKOFF_INITIAL}s → max {BACKOFF_MAX}s")
    _log("=" * 60)

    while True:
        attempt += 1
        start_ts = time.time()
        _log(f"Запуск #{attempt} — {datetime.now().strftime('%H:%M:%S')}")

        try:
            proc = subprocess.run(
                [PYTHON, "-m", MODULE],
                cwd=str(WORKDIR),
                env=env,
            )
            exit_code = proc.returncode
        except KeyboardInterrupt:
            _log("Watchdog остановлен (Ctrl+C). Bye.")
            return
        except Exception as e:
            _log(f"Ошибка запуска subprocess: {e}")
            exit_code = -1

        uptime = time.time() - start_ts

        if exit_code == 0:
            # Штатное завершение (KeyboardInterrupt внутри бота)
            _log(f"Бот завершился штатно (код 0, uptime={uptime:.0f}s). Выходим.")
            return

        _log(f"Бот упал (код {exit_code}, uptime={uptime:.0f}s)")

        # Если работал стабильно — сбрасываем backoff
        if uptime >= STABLE_UPTIME:
            backoff = BACKOFF_INITIAL
            _log("Стабильный uptime — backoff сброшен")
        else:
            backoff = min(backoff * 2, BACKOFF_MAX)

        _log(f"Перезапуск через {backoff}s...")
        try:
            time.sleep(backoff)
        except KeyboardInterrupt:
            _log("Watchdog остановлен (Ctrl+C во время ожидания). Bye.")
            return


if __name__ == "__main__":
    run()
