from app.services.llm.base import LLMAdapter


def get_llm_adapter() -> LLMAdapter:
    # Read settings.LLM_PROVIDER.
    # Return GeminiAdapter() if provider == "gemini".
    # Raise ValueError for any unknown provider string.
    raise NotImplementedError
