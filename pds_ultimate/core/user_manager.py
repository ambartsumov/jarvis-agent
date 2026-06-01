"""
PDS-Ultimate User Manager
============================
Многопользовательская система с динамическим подключением API.

Архитектура:
- При /start бот спрашивает имя
- Если "Вячеслав Амбарцумов" → полный доступ с предустановленными API
- Любой другой пользователь → guided onboarding:
  - Агент объясняет какие инструменты можно подключить
  - Пользователь скидывает API ключи прямо в чат
  - Агент автоматически распознаёт, валидирует и подключает

Каждый пользователь получает:
- Свой профиль с API конфигами
- Свой набор инструментов (tool registry)
- Свою память и контекст
- Изолированные данные

Безопасность:
- API ключи шифруются Fernet (AES-128-CBC)
- Ключ шифрования из ENV или генерируется автоматически
- Ключи НЕ логируются и НЕ отображаются полностью
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any

from pds_ultimate.config import config, logger

# ─── Шифрование API ключей ───────────────────────────────────────────────────

_ENCRYPTION_KEY: bytes | None = None


def _get_encryption_key() -> bytes:
    """Получить или сгенерировать ключ шифрования."""
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY:
        return _ENCRYPTION_KEY

    env_key = os.getenv("PDS_ENCRYPTION_KEY", "")
    if env_key:
        # Используем SHA-256 от пароля → 32 байта → base64 → Fernet key
        raw = hashlib.sha256(env_key.encode()).digest()
        _ENCRYPTION_KEY = base64.urlsafe_b64encode(raw)
    else:
        # Генерируем на основе bot token (стабильный между перезагрузками)
        raw = hashlib.sha256(config.telegram.token.encode()).digest()
        _ENCRYPTION_KEY = base64.urlsafe_b64encode(raw)

    return _ENCRYPTION_KEY


def encrypt_value(value: str) -> str:
    """Зашифровать значение (API ключ)."""
    try:
        from cryptography.fernet import Fernet
        key = _get_encryption_key()
        f = Fernet(key)
        return f.encrypt(value.encode()).decode()
    except ImportError:
        # Fallback: base64 (если cryptography не установлен)
        return "b64:" + base64.b64encode(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Расшифровать значение."""
    try:
        if encrypted.startswith("b64:"):
            return base64.b64decode(encrypted[4:]).decode()
        from cryptography.fernet import Fernet
        key = _get_encryption_key()
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
    except Exception as e:
        logger.warning(f"Decrypt error: {e}")
        return ""


def mask_key(value: str) -> str:
    """Замаскировать ключ для отображения: sk-xxxx...xxxx."""
    if len(value) <= 8:
        return "***"
    return value[:4] + "..." + value[-4:]


# ─── Определения поддерживаемых API ─────────────────────────────────────────

# Каждый API описан: name, description, required_fields, validation_pattern, setup_instructions
SUPPORTED_APIS = {
    "deepseek": {
        "name": "DeepSeek API",
        "description": "AI-модель для рассуждений и генерации текста (мозг агента)",
        "fields": {
            "api_key": {
                "description": "API ключ DeepSeek",
                "pattern": r"sk-[a-zA-Z0-9]{20,}",
                "required": True,
            },
            "base_url": {
                "description": "URL API (обычно https://api.deepseek.com)",
                "default": "https://api.deepseek.com",
                "required": False,
            },
        },
        "setup_guide": (
            "🧠 <b>DeepSeek API</b> — мозг агента\n\n"
            "1. Зайди на https://platform.deepseek.com\n"
            "2. Зарегистрируйся и перейди в API Keys\n"
            "3. Создай новый ключ\n"
            "4. Скопируй и отправь мне ключ (начинается с sk-...)\n\n"
            "💡 Это ОБЯЗАТЕЛЬНЫЙ компонент — без него агент не работает."
        ),
        "category": "core",
        "required_for_start": True,
    },
    "openai": {
        "name": "OpenAI API",
        "description": "GPT-4, GPT-4o — альтернативная AI-модель",
        "fields": {
            "api_key": {
                "description": "API ключ OpenAI",
                "pattern": r"sk-[a-zA-Z0-9\-_]{20,}",
                "required": True,
            },
            "model": {
                "description": "Модель (gpt-4o, gpt-4-turbo и т.д.)",
                "default": "gpt-4o",
                "required": False,
            },
        },
        "setup_guide": (
            "🤖 <b>OpenAI API</b> — GPT-4\n\n"
            "1. Зайди на https://platform.openai.com\n"
            "2. Перейди в API → API Keys\n"
            "3. Создай новый secret key\n"
            "4. Отправь мне ключ (начинается с sk-...)"
        ),
        "category": "llm",
        "required_for_start": False,
    },
    "anthropic": {
        "name": "Anthropic API",
        "description": "Claude — мощная AI-модель для анализа и текстов",
        "fields": {
            "api_key": {
                "description": "API ключ Anthropic",
                "pattern": r"sk-ant-[a-zA-Z0-9\-_]{20,}",
                "required": True,
            },
        },
        "setup_guide": (
            "🔬 <b>Anthropic API</b> — Claude\n\n"
            "1. Зайди на https://console.anthropic.com\n"
            "2. Settings → API Keys\n"
            "3. Создай новый ключ\n"
            "4. Отправь мне ключ (начинается с sk-ant-...)"
        ),
        "category": "llm",
        "required_for_start": False,
    },
    "telegram_bot": {
        "name": "Telegram Bot Token",
        "description": "Токен бота (уже подключён если ты это читаешь)",
        "fields": {
            "token": {
                "description": "Токен бота от @BotFather",
                "pattern": r"\d{8,}:[A-Za-z0-9_-]{35,}",
                "required": True,
            },
        },
        "setup_guide": (
            "🤖 <b>Telegram Bot</b>\n\n"
            "Бот уже работает — этот API подключён автоматически."
        ),
        "category": "messenger",
        "required_for_start": False,
    },
    "whatsapp_green_api": {
        "name": "WhatsApp (Green-API)",
        "description": "WhatsApp интеграция через Green-API",
        "fields": {
            "instance_id": {
                "description": "ID инстанса Green-API",
                "pattern": r"\d{5,}",
                "required": True,
            },
            "api_token": {
                "description": "Токен Green-API",
                "pattern": r"[a-f0-9]{30,}",
                "required": True,
            },
        },
        "setup_guide": (
            "📱 <b>WhatsApp через Green-API</b>\n\n"
            "1. Зайди на https://green-api.com\n"
            "2. Зарегистрируйся и создай инстанс\n"
            "3. Привяжи свой WhatsApp (QR-код)\n"
            "4. Скопируй Instance ID и API Token\n"
            "5. Отправь мне оба значения"
        ),
        "category": "messenger",
        "required_for_start": False,
    },
    "gmail": {
        "name": "Gmail API",
        "description": "Чтение и отправка email через Gmail",
        "fields": {
            "credentials_json": {
                "description": "Содержимое credentials.json от Google Cloud",
                "pattern": r"\{.*client_id.*\}",
                "required": True,
            },
        },
        "setup_guide": (
            "📧 <b>Gmail API</b>\n\n"
            "1. Зайди на https://console.cloud.google.com\n"
            "2. Создай проект → Включи Gmail API\n"
            "3. Credentials → OAuth 2.0 Client ID\n"
            "4. Скачай credentials.json\n"
            "5. Открой файл и отправь мне его содержимое"
        ),
        "category": "email",
        "required_for_start": False,
    },
    "custom_api": {
        "name": "Любой REST API",
        "description": "Подключение произвольного API (любой сервис)",
        "fields": {
            "base_url": {
                "description": "URL API",
                "pattern": r"https?://.+",
                "required": True,
            },
            "api_key": {
                "description": "Ключ авторизации",
                "required": False,
            },
            "auth_header": {
                "description": "Заголовок авторизации (Authorization, X-API-Key и т.д.)",
                "default": "Authorization",
                "required": False,
            },
            "auth_prefix": {
                "description": "Префикс (Bearer, Token и т.д.)",
                "default": "Bearer",
                "required": False,
            },
            "description": {
                "description": "Описание что делает этот API",
                "required": False,
            },
        },
        "setup_guide": (
            "🔌 <b>Подключение любого API</b>\n\n"
            "Отправь мне:\n"
            "• URL API (обязательно)\n"
            "• API ключ (если есть)\n"
            "• Описание что делает API\n\n"
            "Я сам разберусь с форматом и подключу."
        ),
        "category": "custom",
        "required_for_start": False,
    },
}


# ─── Распознавание API из текста ─────────────────────────────────────────────

# Паттерны для автоматического определения типа API ключа из текста
API_KEY_PATTERNS = [
    # (pattern, api_type, field_name)
    (r"sk-[a-zA-Z0-9]{20,}", "deepseek_or_openai", "api_key"),
    (r"sk-ant-[a-zA-Z0-9\-_]{20,}", "anthropic", "api_key"),
    (r"\d{8,}:[A-Za-z0-9_-]{35,}", "telegram_bot", "token"),
    (r"xoxb-[a-zA-Z0-9\-]+", "slack", "token"),
    (r"ghp_[a-zA-Z0-9]{36}", "github", "token"),
    (r"glpat-[a-zA-Z0-9\-_]{20,}", "gitlab", "token"),
    (r"AKIA[A-Z0-9]{16}", "aws", "access_key"),
    (r"AIza[a-zA-Z0-9\-_]{35}", "google", "api_key"),
]


class UserManager:
    """
    Менеджер пользователей.

    Управляет:
    - Регистрация/идентификация пользователей
    - Хранение API конфигов (зашифрованных)
    - Onboarding (пошаговое подключение)
    - Per-user tool registry
    """

    # Имя владельца (полный доступ ко всем API)
    OWNER_NAME = "вячеслав амбарцумов"
    OWNER_ALIASES = [
        "вячеслав амбарцумов",
        "vyacheslav ambartsumov",
        "славик",
        "slavik",
    ]

    def __init__(self):
        self._profiles: dict[int, dict] = {}  # chat_id → profile cache
        self._user_tools: dict[int, Any] = {}  # chat_id → ToolRegistry

    # ─── Идентификация ───────────────────────────────────────────────────

    def is_owner(self, name: str) -> bool:
        """Проверить является ли имя владельцем."""
        normalized = name.strip().lower()
        return normalized in self.OWNER_ALIASES

    def is_registered(self, chat_id: int, db_session) -> bool:
        """Проверить зарегистрирован ли пользователь."""
        from pds_ultimate.core.database import UserProfile
        return db_session.query(UserProfile).filter_by(
            chat_id=chat_id, is_active=True
        ).first() is not None

    def get_profile(self, chat_id: int, db_session) -> dict | None:
        """Получить профиль пользователя."""
        # Кэш
        if chat_id in self._profiles:
            return self._profiles[chat_id]

        from pds_ultimate.core.database import UserProfile
        user = db_session.query(UserProfile).filter_by(
            chat_id=chat_id, is_active=True
        ).first()

        if not user:
            return None

        profile = {
            "id": user.id,
            "chat_id": user.chat_id,
            "name": user.name,
            "role": user.role,
            "is_owner": user.role == "owner",
            "created_at": user.created_at,
            "onboarding_complete": user.onboarding_complete,
            "settings": json.loads(user.settings_json) if user.settings_json else {},
        }

        self._profiles[chat_id] = profile
        return profile

    # ─── Регистрация ─────────────────────────────────────────────────────

    async def register_user(
        self,
        chat_id: int,
        name: str,
        db_session,
    ) -> dict:
        """
        Зарегистрировать нового пользователя.

        Returns:
            profile dict
        """
        from pds_ultimate.core.database import UserProfile

        is_owner = self.is_owner(name)
        role = "owner" if is_owner else "user"

        # Проверяем не зарегистрирован ли уже
        existing = db_session.query(UserProfile).filter_by(
            chat_id=chat_id
        ).first()

        if existing:
            existing.name = name
            existing.role = role
            existing.is_active = True
            if is_owner:
                existing.onboarding_complete = True
        else:
            user = UserProfile(
                chat_id=chat_id,
                name=name,
                role=role,
                onboarding_complete=is_owner,  # Владелец — сразу ready
            )
            db_session.add(user)

        db_session.flush()

        # Если владелец — копируем предустановленные API
        if is_owner:
            await self._setup_owner_apis(chat_id, db_session)

        # Сбрасываем кэш
        self._profiles.pop(chat_id, None)

        profile = self.get_profile(chat_id, db_session)
        logger.info(
            f"User registered: {name} (chat_id={chat_id}, role={role})")
        return profile

    async def _setup_owner_apis(self, chat_id: int, db_session) -> None:
        """Настроить предустановленные API для владельца."""

        # DeepSeek
        self._save_api_config(
            chat_id, "deepseek", {
                "api_key": config.deepseek.api_key,
                "base_url": config.deepseek.base_url,
                "model": config.deepseek.model,
                "fast_model": config.deepseek.fast_model,
            }, db_session, validated=True,
        )

        # Telegram Bot
        self._save_api_config(
            chat_id, "telegram_bot", {
                "token": config.telegram.token,
            }, db_session, validated=True,
        )

        # WhatsApp Green-API (если есть)
        if config.whatsapp.green_api_instance:
            self._save_api_config(
                chat_id, "whatsapp_green_api", {
                    "instance_id": config.whatsapp.green_api_instance,
                    "api_token": config.whatsapp.green_api_token,
                }, db_session, validated=True,
            )

        # Gmail (если есть)
        if config.gmail.enabled:
            self._save_api_config(
                chat_id, "gmail", {
                    "credentials_path": str(config.gmail.credentials_file),
                    "token_path": str(config.gmail.token_file),
                }, db_session, validated=True,
            )

        db_session.flush()
        logger.info(f"Owner APIs configured for chat_id={chat_id}")

    # ─── API Configuration ───────────────────────────────────────────────

    def _save_api_config(
        self,
        chat_id: int,
        api_type: str,
        config_data: dict,
        db_session,
        validated: bool = False,
    ) -> None:
        """Сохранить конфиг API (с шифрованием ключей)."""
        from pds_ultimate.core.database import UserAPIConfig

        # Шифруем чувствительные поля
        encrypted_data = {}
        sensitive_fields = {"api_key", "token", "api_token", "secret",
                            "password", "credentials_json"}

        for k, v in config_data.items():
            if k in sensitive_fields and v:
                encrypted_data[k] = encrypt_value(str(v))
            else:
                encrypted_data[k] = str(v) if v else ""

        data_json = json.dumps(encrypted_data, ensure_ascii=False)

        # Upsert
        existing = db_session.query(UserAPIConfig).filter_by(
            chat_id=chat_id, api_type=api_type
        ).first()

        if existing:
            existing.config_data = data_json
            existing.is_validated = validated
            existing.is_active = True
        else:
            entry = UserAPIConfig(
                chat_id=chat_id,
                api_type=api_type,
                api_name=SUPPORTED_APIS.get(
                    api_type, {}).get("name", api_type),
                config_data=data_json,
                is_validated=validated,
                is_active=True,
            )
            db_session.add(entry)

    def get_api_config(
        self,
        chat_id: int,
        api_type: str,
        db_session,
    ) -> dict | None:
        """Получить расшифрованный конфиг API."""
        from pds_ultimate.core.database import UserAPIConfig

        entry = db_session.query(UserAPIConfig).filter_by(
            chat_id=chat_id, api_type=api_type, is_active=True,
        ).first()

        if not entry:
            return None

        data = json.loads(entry.config_data)

        # Расшифровываем
        decrypted = {}
        for k, v in data.items():
            if v and (v.startswith("gAAAAA") or v.startswith("b64:")):
                decrypted[k] = decrypt_value(v)
            else:
                decrypted[k] = v

        return decrypted

    def get_user_apis(self, chat_id: int, db_session) -> list[dict]:
        """Получить все подключённые API пользователя."""
        from pds_ultimate.core.database import UserAPIConfig

        entries = db_session.query(UserAPIConfig).filter_by(
            chat_id=chat_id, is_active=True,
        ).all()

        result = []
        for entry in entries:
            result.append({
                "api_type": entry.api_type,
                "api_name": entry.api_name,
                "is_validated": entry.is_validated,
                "created_at": entry.created_at,
            })
        return result

    def remove_api(self, chat_id: int, api_type: str, db_session) -> bool:
        """Отключить API."""
        from pds_ultimate.core.database import UserAPIConfig

        entry = db_session.query(UserAPIConfig).filter_by(
            chat_id=chat_id, api_type=api_type
        ).first()

        if entry:
            entry.is_active = False
            return True
        return False

    # ─── Автоматическое распознавание API из текста ──────────────────────

    async def detect_and_save_api(
        self,
        chat_id: int,
        text: str,
        db_session,
    ) -> dict | None:
        """
        Автоматически определить тип API ключа из текста пользователя.

        Пользователь может просто скинуть ключ в чат — агент сам поймёт.

        Returns:
            {"api_type": ..., "field": ..., "masked_value": ...} или None
        """
        text = text.strip()

        # 1. Проверяем по паттернам
        for pattern, api_type, field_name in API_KEY_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value = match.group(0)

                # Различаем DeepSeek и OpenAI
                if api_type == "deepseek_or_openai":
                    if "deepseek" in text.lower() or len(value) == 35:
                        api_type = "deepseek"
                    else:
                        api_type = "openai"

                self._save_api_config(
                    chat_id, api_type,
                    {field_name: value},
                    db_session, validated=False,
                )

                return {
                    "api_type": api_type,
                    "field": field_name,
                    "masked_value": mask_key(value),
                    "api_name": SUPPORTED_APIS.get(api_type, {}).get("name", api_type),
                }

        # 2. Проверяем JSON (credentials.json от Google)
        try:
            data = json.loads(text)
            if "client_id" in str(data) and "client_secret" in str(data):
                self._save_api_config(
                    chat_id, "gmail",
                    {"credentials_json": text},
                    db_session, validated=False,
                )
                return {
                    "api_type": "gmail",
                    "field": "credentials_json",
                    "masked_value": "[Google OAuth credentials]",
                    "api_name": "Gmail API",
                }
        except (json.JSONDecodeError, ValueError):
            pass

        # 3. Проверяем URL (custom API)
        url_match = re.search(r"(https?://[^\s]+)", text)
        if url_match and ("api" in text.lower() or "endpoint" in text.lower()):
            url = url_match.group(1)
            # Ищем также ключ в тексте
            key_match = re.search(
                r"(?:key|token|secret)[:\s=]+([a-zA-Z0-9\-_]{16,})", text, re.I)
            config_data = {"base_url": url}
            if key_match:
                config_data["api_key"] = key_match.group(1)

            self._save_api_config(
                chat_id, "custom_api",
                config_data, db_session, validated=False,
            )
            return {
                "api_type": "custom_api",
                "field": "base_url",
                "masked_value": url[:50],
                "api_name": "Custom API",
            }

        return None

    # ─── Валидация API ───────────────────────────────────────────────────

    async def validate_api(
        self,
        chat_id: int,
        api_type: str,
        db_session,
    ) -> tuple[bool, str]:
        """
        Проверить работоспособность API.

        Returns:
            (success, message)
        """
        api_config = self.get_api_config(chat_id, api_type, db_session)
        if not api_config:
            return False, "API не найден"

        try:
            if api_type in ("deepseek", "openai"):
                return await self._validate_llm_api(api_type, api_config)
            elif api_type == "anthropic":
                return await self._validate_anthropic(api_config)
            elif api_type == "whatsapp_green_api":
                return await self._validate_whatsapp(api_config)
            elif api_type == "gmail":
                return True, "Gmail требует OAuth авторизацию через браузер"
            elif api_type == "custom_api":
                return await self._validate_custom_api(api_config)
            else:
                return True, "Валидация не реализована — ключ сохранён"
        except Exception as e:
            return False, f"Ошибка валидации: {e}"

    async def _validate_llm_api(
        self, api_type: str, api_config: dict
    ) -> tuple[bool, str]:
        """Валидировать DeepSeek/OpenAI API."""
        import httpx

        base_url = api_config.get("base_url", "")
        if api_type == "deepseek":
            base_url = base_url or "https://api.deepseek.com"
        elif api_type == "openai":
            base_url = base_url or "https://api.openai.com"

        api_key = api_config.get("api_key", "")
        if not api_key:
            return False, "API ключ пуст"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{base_url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    models = resp.json().get("data", [])
                    model_names = [m.get("id", "") for m in models[:5]]
                    return True, f"✅ Подключён! Модели: {', '.join(model_names)}"
                elif resp.status_code == 401:
                    return False, "❌ Неверный API ключ"
                else:
                    return False, f"❌ Ошибка {resp.status_code}: {resp.text[:100]}"
        except httpx.TimeoutException:
            return False, "❌ Таймаут — API не отвечает"
        except Exception as e:
            return False, f"❌ Ошибка подключения: {e}"

    async def _validate_anthropic(self, api_config: dict) -> tuple[bool, str]:
        """Валидировать Anthropic API."""
        import httpx

        api_key = api_config.get("api_key", "")
        if not api_key:
            return False, "API ключ пуст"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 10,
                        "messages": [{"role": "user", "content": "ping"}],
                    },
                )
                if resp.status_code == 200:
                    return True, "✅ Anthropic API подключён!"
                elif resp.status_code == 401:
                    return False, "❌ Неверный API ключ"
                else:
                    return False, f"❌ Ошибка {resp.status_code}"
        except Exception as e:
            return False, f"❌ Ошибка: {e}"

    async def _validate_whatsapp(self, api_config: dict) -> tuple[bool, str]:
        """Валидировать WhatsApp Green-API."""
        import httpx

        instance = api_config.get("instance_id", "")
        token = api_config.get("api_token", "")
        if not instance or not token:
            return False, "Instance ID или Token пуст"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"https://api.green-api.com/waInstance{instance}"
                    f"/getStateInstance/{token}"
                )
                if resp.status_code == 200:
                    state = resp.json().get("stateInstance", "")
                    if state == "authorized":
                        return True, "✅ WhatsApp подключён и авторизован!"
                    return False, f"⚠️ Статус: {state} — нужна авторизация QR"
                return False, f"❌ Ошибка {resp.status_code}"
        except Exception as e:
            return False, f"❌ Ошибка: {e}"

    async def _validate_custom_api(self, api_config: dict) -> tuple[bool, str]:
        """Валидировать custom API (просто пинг)."""
        import httpx

        url = api_config.get("base_url", "")
        if not url:
            return False, "URL пуст"

        try:
            headers = {}
            api_key = api_config.get("api_key", "")
            if api_key:
                auth_header = api_config.get("auth_header", "Authorization")
                auth_prefix = api_config.get("auth_prefix", "Bearer")
                headers[auth_header] = f"{auth_prefix} {api_key}"

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, headers=headers)
                return True, f"✅ API отвечает (status {resp.status_code})"
        except Exception as e:
            return False, f"❌ Ошибка: {e}"

    # ─── Onboarding ──────────────────────────────────────────────────────

    def get_onboarding_message(self) -> str:
        """Сообщение для нового пользователя."""
        apis_list = []
        for key, api_info in SUPPORTED_APIS.items():
            if key in ("telegram_bot",):  # Скрываем уже подключённые
                continue
            required = "⚡ ОБЯЗАТЕЛЬНО" if api_info.get(
                "required_for_start") else "📌 Опционально"
            apis_list.append(
                f"• <b>{api_info['name']}</b> — {api_info['description']} [{required}]"
            )

        return (
            "🔧 <b>Настройка твоего агента</b>\n\n"
            "Чтобы я мог работать, мне нужны API ключи от сервисов.\n"
            "Ты можешь подключить любые из них:\n\n"
            + "\n".join(apis_list) + "\n\n"
            "📋 <b>Как подключить:</b>\n"
            "• Просто скинь мне API ключ — я сам определю что это\n"
            "• Или напиши 'подключить DeepSeek' — я дам подробную инструкцию\n"
            "• Или напиши 'мои api' — покажу что уже подключено\n\n"
            "💡 Минимум для работы: <b>DeepSeek API</b> (мозг агента)\n\n"
            "Когда будешь готов — просто начни пользоваться! 🚀"
        )

    def get_connected_apis_message(
        self, chat_id: int, db_session
    ) -> str:
        """Показать подключённые API."""
        apis = self.get_user_apis(chat_id, db_session)

        if not apis:
            return (
                "📡 <b>Подключённые API</b>\n\n"
                "Пока ничего не подключено.\n"
                "Скинь мне API ключ или напиши 'подключить' + название сервиса."
            )

        lines = ["📡 <b>Подключённые API:</b>\n"]
        for api in apis:
            status = "✅" if api["is_validated"] else "⏳ (не проверен)"
            lines.append(f"• {api['api_name']} {status}")

        lines.append(
            "\n💡 Чтобы подключить ещё — скинь API ключ или напиши 'подключить'")
        return "\n".join(lines)

    def get_api_setup_guide(self, api_type: str) -> str:
        """Инструкция по подключению конкретного API."""
        api_info = SUPPORTED_APIS.get(api_type)
        if not api_info:
            return f"❌ Неизвестный API: {api_type}"
        return api_info["setup_guide"]

    # ─── Кэш ─────────────────────────────────────────────────────────────

    def invalidate_cache(self, chat_id: int) -> None:
        """Сбросить кэш профиля."""
        self._profiles.pop(chat_id, None)
        self._user_tools.pop(chat_id, None)


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

user_manager = UserManager()
