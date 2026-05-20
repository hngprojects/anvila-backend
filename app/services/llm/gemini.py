import asyncio
from typing import ClassVar

import google.generativeai as genai

from app.core.config import settings
from app.services.llm.base import LLMAdapter
from app.services.llm.types import LLMResponse


class GeminiAdapter(LLMAdapter):
    SYSTEM_PROMPT: ClassVar[str] = ""

    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model_name: str = "gemini-2.0-flash"
        self._model = genai.GenerativeModel(self._model_name)

    def build_prompt(self, prompt: str) -> str:
        return prompt

    async def generate(self, prompt: str) -> LLMResponse:
        response = await asyncio.wait_for(
            self._model.generate_content_async(prompt),
            timeout=settings.GEMINI_TIMEOUT_SECONDS,
        )
        usage = getattr(response, "usage_metadata", None)
        return LLMResponse(
            content=response.text,
            input_tokens=getattr(usage, "prompt_token_count", 0),
            output_tokens=getattr(usage, "candidates_token_count", 0),
            total_tokens=getattr(usage, "total_token_count", 0),
            model=self._model_name,
        )

    async def is_healthy(self) -> bool:
        try:
            await self.generate("ping")
            return True
        except Exception:
            return False
