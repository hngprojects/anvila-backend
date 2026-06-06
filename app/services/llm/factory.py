from app.core.config import settings
from app.services.llm.base import LLMAdapter
from app.services.llm.gemini import GeminiAdapter


def get_llm_adapter() -> LLMAdapter:
    if settings.LLM_PROVIDER == "gemini":
        return GeminiAdapter()
    raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER!r}")
