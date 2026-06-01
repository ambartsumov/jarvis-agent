import os
import sys

from app.tool import BaseTool


class AskHuman(BaseTool):
    """Add a tool to ask human for help."""

    name: str = "ask_human"
    description: str = "Use this tool to ask human for help."
    parameters: str = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question you want to ask human.",
            }
        },
        "required": ["inquire"],
    }

    async def execute(self, inquire: str) -> str:
        q = (inquire or "").strip()
        if os.environ.get("PDS_BRIDGE_MODE") == "1" or not sys.stdin.isatty():
            return (
                f"Вопрос пользователю (ответь в следующем сообщении Telegram):\n{q}"
            )
        return input(f"""Bot: {q}\n\nYou: """).strip()
