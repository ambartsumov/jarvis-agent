"""Unified async LLM client — native tool-calling, retries, JSON mode, token accounting."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from pds_ultimate.config import config, logger
from pds_ultimate.core.llm.router import ModelRouter, TaskKind


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    """Production LLM client: native function-calling + retry + structured output."""

    def __init__(self) -> None:
        self.router = ModelRouter()
        self._client: httpx.AsyncClient | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        from pds_ultimate.config import proxy_if_available

        proxy = proxy_if_available(config.deepseek.proxy) or None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.deepseek.timeout, connect=30.0),
            proxy=proxy,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._started = True
        logger.info("LLM client started (DeepSeek, native tool-calling)")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._started = False

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        kind: TaskKind = TaskKind.STEP,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Full completion with optional native tool-calling. Returns LLMResponse."""
        provider, base_url, model = self.router.select(kind)
        api_key = self.router.api_key_for(provider)
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY не задан")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.deepseek.temperature,
            "max_tokens": max_tokens or config.deepseek.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if json_mode and not tools:
            payload["response_format"] = {"type": "json_object"}

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        last_error: Exception | None = None
        for attempt in range(config.deepseek.max_retries):
            try:
                assert self._client is not None
                resp = await self._client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                msg = choice["message"]
                usage = data.get("usage", {})
                return LLMResponse(
                    content=(msg.get("content") or "").strip(),
                    tool_calls=msg.get("tool_calls") or [],
                    finish_reason=choice.get("finish_reason", "stop"),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                # 4xx (except 429) won't recover by retry
                if exc.response.status_code not in (429, 500, 502, 503, 504):
                    logger.error(f"LLM HTTP {exc.response.status_code}: {exc.response.text[:300]}")
                    raise
                await asyncio.sleep(min(2 ** attempt, 16))
            except Exception as exc:
                last_error = exc
                logger.warning(f"LLM attempt {attempt + 1} failed: {exc}")
                await asyncio.sleep(min(2 ** attempt, 16))

        raise RuntimeError(f"LLM failed after retries: {last_error}")

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.CHAT,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        resp = await self.complete(
            messages, kind=kind, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )
        return resp.content

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        kind: TaskKind = TaskKind.REASON,
    ) -> dict[str, Any]:
        raw = await self.chat(messages, kind=kind, json_mode=True, temperature=0.2)
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise


llm_client = LLMClient()
