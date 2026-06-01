"""Gmail — send/read/search via shared Google OAuth token."""

from __future__ import annotations

import asyncio
import base64
from email.mime.text import MIMEText

from app.integrations.google_auth import build_google_service


def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from Gmail message payload."""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")
    for part in payload.get("parts", []):
        body = _extract_body(part)
        if body:
            return body
    return ""


def _headers(payload: dict) -> dict:
    return {h["name"]: h["value"] for h in payload.get("headers", [])}


class GmailClient:
    def _service(self):
        svc, reason = build_google_service("gmail", "v1")
        return svc, reason

    async def send(self, to: str, subject: str, body: str) -> str:
        def _send() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            msg = MIMEText(body, "plain", "utf-8")
            msg["to"] = to
            msg["subject"] = subject
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            result = svc.users().messages().send(
                userId="me", body={"raw": raw}).execute()
            return f"OK: email sent id={result.get('id', '?')} → {to}"

        return await asyncio.to_thread(_send)

    async def reply(self, message_id: str, to: str, subject: str, body: str, thread_id: str = "") -> str:
        """Reply to an email thread."""
        def _reply() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            msg = MIMEText(body, "plain", "utf-8")
            msg["to"] = to
            msg["subject"] = subject if subject.startswith(
                "Re:") else f"Re: {subject}"
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            payload: dict = {"raw": raw}
            if thread_id:
                payload["threadId"] = thread_id
            result = svc.users().messages().send(userId="me", body=payload).execute()
            return f"OK: reply sent id={result.get('id', '?')} → {to}"

        return await asyncio.to_thread(_reply)

    async def list_unread(self, max_results: int = 5) -> str:
        return await self._list_messages("is:unread", max_results)

    async def list_inbox(self, max_results: int = 10) -> str:
        return await self._list_messages("in:inbox", max_results)

    async def search(self, query: str, max_results: int = 10) -> str:
        """Search Gmail with any Gmail query (from:, subject:, after:, etc.)."""
        return await self._list_messages(query, max_results)

    async def _list_messages(self, query: str, max_results: int) -> str:
        def _list() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            resp = svc.users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
            ids = [m["id"] for m in resp.get("messages", [])]
            lines = []
            for mid in ids:
                m = svc.users().messages().get(
                    userId="me", id=mid, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                h = _headers(m.get("payload", {}))
                snippet = m.get("snippet", "")[:120]
                lines.append(
                    f"[{mid}] {h.get('Date', '?')[:16]} | "
                    f"From: {h.get('From', '?')} | "
                    f"Subject: {h.get('Subject', '(no subject)')} | "
                    f"{snippet}…"
                )
            return "\n".join(lines) if lines else f"OK: no messages for '{query}'"

        return await asyncio.to_thread(_list)

    async def read(self, message_id: str) -> str:
        """Read full email body by message id."""
        def _read() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            m = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
            h = _headers(m.get("payload", {}))
            body = _extract_body(m.get("payload", {}))
            return (
                f"From: {h.get('From', '?')}\n"
                f"To: {h.get('To', '?')}\n"
                f"Date: {h.get('Date', '?')}\n"
                f"Subject: {h.get('Subject', '(no subject)')}\n"
                f"Thread-ID: {m.get('threadId', '?')}\n"
                f"---\n{body or '(empty body)'}"
            )

        return await asyncio.to_thread(_read)

    async def read_thread(self, thread_id: str) -> str:
        """Read all messages in a thread (chain of emails)."""
        def _thread() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            t = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
            parts = []
            for msg in t.get("messages", []):
                h = _headers(msg.get("payload", {}))
                body = _extract_body(msg.get("payload", {}))
                parts.append(
                    f"── {h.get('Date', '?')[:16]} | {h.get('From', '?')}\n{body[:800] or '(empty)'}"
                )
            return f"Thread {thread_id} ({len(parts)} messages):\n\n" + "\n\n".join(parts)

        return await asyncio.to_thread(_thread)

    async def mark_read(self, message_id: str) -> str:
        """Mark a message as read."""
        def _mark() -> str:
            svc, reason = self._service()
            if not svc:
                return f"ERROR: {reason}"
            svc.users().messages().modify(
                userId="me", id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return f"OK: marked {message_id} as read"

        return await asyncio.to_thread(_mark)


gmail = GmailClient()
