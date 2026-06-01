"""
PDS-Ultimate Gmail Integration (Dual Account)
================================================
Интеграция с Gmail API — два аккаунта (рабочий + личный).

По ТЗ:
- Чтение входящих писем с обоих аккаунтов
- Отправка писем (отчёты каждые 3 дня)
- Ответ на письма в стиле владельца
- OAuth2 авторизация через credentials.json
"""

from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from pds_ultimate.config import BASE_DIR, DATA_DIR, config, logger


class GmailAccount:
    """Один Gmail аккаунт с отдельным service."""

    def __init__(self, name: str, credentials_file: Path, token_file: Path):
        self.name = name
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None

    def build_service(self):
        """Построить Gmail service (синхронно)."""
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        from pds_ultimate.integrations.google_auth import GOOGLE_SCOPES

        SCOPES = GOOGLE_SCOPES

        creds = None

        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(
                str(self.token_file), SCOPES,
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials не найден: "
                        f"{self.credentials_file}"
                    )
                # НЕ запускаем run_local_server — он блокирует навсегда.
                # Вместо этого — ошибка, пусть пользователь запустит OAuth отдельно.
                raise RuntimeError(
                    f"Gmail токен не найден: {self.token_file}. "
                    f"Запустите OAuth вручную: "
                    f"python -m pds_ultimate.integrations.gmail_auth"
                )

            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as f:
                f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    @property
    def service(self):
        return self._service


class GmailClient:
    """
    Клиент Gmail API с поддержкой двух аккаунтов (рабочий + личный).

    Жизненный цикл:
        client = GmailClient()
        await client.start()        # OAuth2 авторизация обоих
        emails = await client.get_unread()  # Из обоих аккаунтов
        await client.send_email(to, subject, body, account="work")
        await client.stop()
    """

    def __init__(self):
        self._accounts: dict[str, GmailAccount] = {}
        self._started = False

    async def start(self) -> None:
        """Авторизация в Gmail через OAuth2 — оба аккаунта."""
        if self._started:
            return

        if not config.gmail.enabled:
            logger.warning("Gmail отключён (GMAIL_ENABLED=false)")
            return

        import asyncio
        loop = asyncio.get_event_loop()

        GMAIL_TIMEOUT = 10  # секунд на подключение (без браузера)

        creds_dir = BASE_DIR / "credentials"

        # Рабочий аккаунт
        work_creds = creds_dir / "gmail_work.json"
        if work_creds.exists():
            try:
                account = GmailAccount(
                    name="work",
                    credentials_file=work_creds,
                    token_file=DATA_DIR / "gmail_token_work.json",
                )
                await asyncio.wait_for(
                    loop.run_in_executor(None, account.build_service),
                    timeout=GMAIL_TIMEOUT,
                )
                self._accounts["work"] = account
                logger.info("Gmail WORK аккаунт подключён ✅")
            except asyncio.TimeoutError:
                logger.warning("  ⚠ Gmail WORK: таймаут подключения")
            except Exception as e:
                logger.warning(f"  ⚠ Gmail WORK: {e}")

        # Личный аккаунт
        personal_creds = creds_dir / "gmail_personal.json"
        if personal_creds.exists():
            try:
                account = GmailAccount(
                    name="personal",
                    credentials_file=personal_creds,
                    token_file=DATA_DIR / "gmail_token_personal.json",
                )
                await asyncio.wait_for(
                    loop.run_in_executor(None, account.build_service),
                    timeout=GMAIL_TIMEOUT,
                )
                self._accounts["personal"] = account
                logger.info("Gmail PERSONAL аккаунт подключён ✅")
            except asyncio.TimeoutError:
                logger.warning("  ⚠ Gmail PERSONAL: таймаут подключения")
            except Exception as e:
                logger.warning(f"  ⚠ Gmail PERSONAL: {e}")

        # Fallback: gmail.json (единый файл)
        if not self._accounts:
            fallback_creds = creds_dir / "gmail.json"
            if fallback_creds.exists():
                try:
                    account = GmailAccount(
                        name="default",
                        credentials_file=fallback_creds,
                        token_file=DATA_DIR / "gmail_token.json",
                    )
                    await asyncio.wait_for(
                        loop.run_in_executor(None, account.build_service),
                        timeout=GMAIL_TIMEOUT,
                    )
                    self._accounts["default"] = account
                    logger.info("Gmail DEFAULT аккаунт подключён ✅")
                except asyncio.TimeoutError:
                    logger.warning("  ⚠ Gmail DEFAULT: таймаут подключения")
                except Exception as e:
                    logger.warning(f"  ⚠ Gmail: {e}")

        if self._accounts:
            self._started = True
            names = ", ".join(self._accounts.keys())
            logger.info(f"Gmail API подключён ({names})")
        else:
            logger.warning("Gmail: ни один аккаунт не подключён")

    async def stop(self) -> None:
        """Отключение."""
        self._accounts.clear()
        self._started = False
        logger.info("Gmail API отключён")

    def _get_service(self, account: Optional[str] = None):
        """Получить service нужного аккаунта."""
        if account and account in self._accounts:
            return self._accounts[account].service
        # Первый доступный
        if self._accounts:
            return next(iter(self._accounts.values())).service
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # Чтение почты
    # ═══════════════════════════════════════════════════════════════════════

    async def get_unread(self, max_results: int = 10, account: Optional[str] = None) -> list[dict]:
        """
        Получить непрочитанные письма.
        account: "work", "personal" или None (все аккаунты).

        Returns:
            [{"id", "from", "subject", "body", "date", "account"}, ...]
        """
        if not self._started:
            return []

        import asyncio
        loop = asyncio.get_event_loop()

        if account:
            return await loop.run_in_executor(
                None, self._fetch_unread, account, max_results,
            )

        # Из всех аккаунтов
        all_emails = []
        for acc_name in self._accounts:
            emails = await loop.run_in_executor(
                None, self._fetch_unread, acc_name, max_results,
            )
            all_emails.extend(emails)
        return all_emails

    def _fetch_unread(self, account: str, max_results: int) -> list[dict]:
        """Синхронная выборка непрочитанных."""
        service = self._get_service(account)
        if not service:
            return []

        try:
            result = service.users().messages().list(
                userId="me",
                q="is:unread",
                maxResults=max_results,
            ).execute()

            messages = result.get("messages", [])
            emails = []

            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full",
                ).execute()

                email_data = self._parse_email(msg)
                if email_data:
                    email_data["account"] = account
                    emails.append(email_data)

            logger.info(
                f"Gmail [{account}]: получено {len(emails)} непрочитанных")
            return emails

        except Exception as e:
            logger.error(f"Ошибка чтения Gmail: {e}")
            return []

    def _parse_email(self, msg: dict) -> Optional[dict]:
        """Распарсить raw email в dict."""
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        # Извлекаем тело
        body = self._extract_body(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", "(без темы)"),
            "date": headers.get("date", ""),
            "body": body[:5000],  # Ограничиваем размер
            "snippet": msg.get("snippet", ""),
        }

    def _extract_body(self, payload: dict) -> str:
        """Извлечь текст из payload (рекурсивно для multipart)."""
        if payload.get("mimeType") == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

            # Рекурсия для вложенных multipart
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        return ""

    # ═══════════════════════════════════════════════════════════════════════
    # Отправка почты
    # ═══════════════════════════════════════════════════════════════════════

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        account: Optional[str] = None,
    ) -> dict:
        """
        Отправить письмо.

        Args:
            to: Адресат
            subject: Тема
            body: Текст письма
            html: HTML-формат или plain text

        Returns:
            {"id": "...", "status": "sent"} или {"error": "..."}
        """
        if not self._started:
            return {"error": "Gmail не подключён"}

        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._send, to, subject, body, html, account,
        )

    def _send(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        account: Optional[str] = None,
    ) -> dict:
        """Синхронная отправка."""
        service = self._get_service(account)
        if not service:
            return {"error": "Gmail аккаунт не найден"}

        try:
            message = MIMEMultipart()
            message["to"] = to
            message["from"] = config.gmail.owner_email
            message["subject"] = subject

            mime_type = "html" if html else "plain"
            message.attach(MIMEText(body, mime_type, "utf-8"))

            raw = base64.urlsafe_b64encode(
                message.as_bytes()
            ).decode("utf-8")

            result = service.users().messages().send(
                userId="me",
                body={"raw": raw},
            ).execute()

            logger.info(f"Gmail: письмо отправлено → {to} ({subject})")
            return {"id": result.get("id", ""), "status": "sent"}

        except Exception as e:
            logger.error(f"Ошибка отправки Gmail: {e}")
            return {"error": str(e)}

    async def reply_to(
        self,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
        account: Optional[str] = None,
    ) -> dict:
        """Ответить на письмо (в том же треде)."""
        if not self._started:
            return {"error": "Gmail не подключён"}

        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._reply, thread_id, message_id, to, subject, body, account,
        )

    def _reply(
        self,
        thread_id: str,
        message_id: str,
        to: str,
        subject: str,
        body: str,
        account: Optional[str] = None,
    ) -> dict:
        """Синхронный ответ на письмо."""
        service = self._get_service(account)
        if not service:
            return {"error": "Gmail аккаунт не найден"}

        try:
            message = MIMEMultipart()
            message["to"] = to
            message["from"] = config.gmail.owner_email
            message["subject"] = f"Re: {subject}" if not subject.startswith(
                "Re:") else subject
            message["In-Reply-To"] = message_id
            message["References"] = message_id

            message.attach(MIMEText(body, "plain", "utf-8"))

            raw = base64.urlsafe_b64encode(
                message.as_bytes()
            ).decode("utf-8")

            result = service.users().messages().send(
                userId="me",
                body={"raw": raw, "threadId": thread_id},
            ).execute()

            logger.info(f"Gmail: ответ отправлен → {to}")
            return {"id": result.get("id", ""), "status": "sent"}

        except Exception as e:
            logger.error(f"Ошибка ответа Gmail: {e}")
            return {"error": str(e)}

    async def get_inbox(self, max_results: int = 20, account: Optional[str] = None) -> list[dict]:
        """
        Получить входящие письма (включая прочитанные).
        account: "work", "personal" или None (все аккаунты).
        """
        if not self._started:
            return []

        import asyncio
        loop = asyncio.get_event_loop()

        if account:
            return await loop.run_in_executor(
                None, self._fetch_inbox, account, max_results,
            )

        all_emails = []
        for acc_name in self._accounts:
            emails = await loop.run_in_executor(
                None, self._fetch_inbox, acc_name, max_results,
            )
            all_emails.extend(emails)
        return all_emails

    def _fetch_inbox(self, account: str, max_results: int) -> list[dict]:
        """Синхронная выборка входящих."""
        service = self._get_service(account)
        if not service:
            return []

        try:
            result = service.users().messages().list(
                userId="me",
                q="in:inbox",
                maxResults=max_results,
            ).execute()

            messages = result.get("messages", [])
            emails = []
            for msg_ref in messages:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="full",
                ).execute()
                email_data = self._parse_email(msg)
                if email_data:
                    email_data["account"] = account
                    emails.append(email_data)

            logger.info(f"Gmail [{account}]: получено {len(emails)} входящих")
            return emails
        except Exception as e:
            logger.error(f"Ошибка чтения inbox Gmail: {e}")
            return []

    async def get_thread(self, thread_id: str, account: Optional[str] = None) -> list[dict]:
        """
        Получить все письма из треда (цепочки ответов).
        Возвращает список писем в хронологическом порядке.
        """
        if not self._started:
            return []

        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fetch_thread, thread_id, account,
        )

    def _fetch_thread(self, thread_id: str, account: Optional[str] = None) -> list[dict]:
        """Синхронная выборка треда."""
        service = self._get_service(account)
        if not service:
            return []

        try:
            thread = service.users().threads().get(
                userId="me",
                id=thread_id,
                format="full",
            ).execute()

            messages = thread.get("messages", [])
            emails = []
            for msg in messages:
                email_data = self._parse_email(msg)
                if email_data:
                    email_data["thread_id"] = thread_id
                    emails.append(email_data)

            logger.info(f"Gmail: тред {thread_id} — {len(emails)} писем")
            return emails
        except Exception as e:
            logger.error(f"Ошибка чтения треда Gmail: {e}")
            return []

    async def mark_as_read(self, message_id: str, account: Optional[str] = None) -> bool:
        """Пометить как прочитанное."""
        if not self._started:
            return False

        service = self._get_service(account)
        if not service:
            return False

        import asyncio
        loop = asyncio.get_event_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"removeLabelIds": ["UNREAD"]},
                ).execute(),
            )
            return True
        except Exception as e:
            logger.error(f"Ошибка mark_as_read: {e}")
            return False


# ─── Глобальный экземпляр ────────────────────────────────────────────────────

gmail_client = GmailClient()
