from google import genai

from app.core.config import settings
from app.services.llm.base import LLMAdapter
from app.services.llm.types import LLMResponse


class GeminiAdapter(LLMAdapter):
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model_name: str = settings.GEMINI_MODEL_NAME

    def build_prompt(self, prompt: str) -> str:
        return prompt

    async def generate(self, prompt: str) -> LLMResponse:
        response = self.client.models.generate_content(model=self._model_name, contents=prompt)
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
