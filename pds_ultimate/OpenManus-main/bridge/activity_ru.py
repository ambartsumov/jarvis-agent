"""Russian activity titles for bridge progress events."""

from __future__ import annotations


def tool_title(name: str) -> str:
    n = (name or "tool").lower()
    if "calendar" in n:
        return "📅 Календарь"
    if "email" in n:
        return "📧 Почта"
    if n == "bash":
        return "💻 Терминал"
    if "browser" in n:
        return "🌐 Браузер"
    if "remember" in n:
        return "💾 Запись в память"
    if "recall" in n or "memory" in n:
        return "🧠 Память"
    if "web_search" in n or "search" in n:
        return "🔍 Поиск в интернете"
    if "desktop" in n:
        return "🖥️ Рабочий стол"
    if "terminate" in n:
        return "✅ Завершение"
    if "str_replace" in n or "editor" in n:
        return "📝 Редактор файлов"
    if "python" in n:
        return "🐍 Python"
    if "ask_human" in n:
        return "❓ Уточнение"
    return f"🔧 {name}"
