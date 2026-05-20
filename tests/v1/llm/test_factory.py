import pytest

from app.core.config import settings
from app.services.llm.factory import get_llm_adapter
from app.services.llm.gemini import GeminiAdapter


def test_factory_returns_gemini_adapter_when_provider_is_gemini(mocker, monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    mocker.patch("app.services.llm.gemini.genai.configure")
    mocker.patch("app.services.llm.gemini.genai.GenerativeModel")

    adapter = get_llm_adapter()
    assert isinstance(adapter, GeminiAdapter)


def test_factory_raises_value_error_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_llm_adapter()
