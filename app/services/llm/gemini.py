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
        response = await self._model.generate_content_async(prompt)
        usage = response.usage_metadata
        return LLMResponse(
            content=response.text,
            input_tokens=usage.prompt_token_count,
            output_tokens=usage.candidates_token_count,
            total_tokens=usage.total_token_count,
            model=self._model_name,
        )

    async def is_healthy(self) -> bool:
        try:
            await self.generate("ping")
            return True
        except Exception:
            return False
