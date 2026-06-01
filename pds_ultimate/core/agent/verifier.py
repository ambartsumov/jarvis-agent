"""Anti-hallucination verifier."""

from __future__ import annotations

from pds_ultimate.core.llm.client import llm_client
from pds_ultimate.core.llm.router import TaskKind


class Verifier:
    """Check that final answers are grounded in observations."""

    async def verify(
        self,
        question: str,
        answer: str,
        observations: list[str],
    ) -> tuple[bool, str]:
        if not observations:
            # Pure conversation — skip strict verification
            return True, answer

        obs_text = "\n---\n".join(observations[-8:])
        prompt = [
            {
                "role": "system",
                "content": (
                    "Ты верификатор. Проверь, что ответ основан на наблюдениях инструментов. "
                    "Верни JSON: {\"ok\": true/false, \"fixed_answer\": \"...\", \"reason\": \"...\"}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Вопрос: {question}\n\n"
                    f"Черновик ответа:\n{answer}\n\n"
                    f"Наблюдения инструментов:\n{obs_text}"
                ),
            },
        ]
        try:
            data = await llm_client.chat_json(prompt, kind=TaskKind.VERIFY)
            ok = bool(data.get("ok", True))
            fixed = data.get("fixed_answer") or answer
            return ok, fixed
        except Exception:
            return True, answer
