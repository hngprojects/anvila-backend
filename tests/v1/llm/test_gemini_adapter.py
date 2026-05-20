from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.gemini import GeminiAdapter
from app.services.llm.types import LLMResponse


@pytest.fixture
def patched_genai(mocker):
    """Patch google-generativeai so GeminiAdapter can be constructed without
    a real API key and so generate_content_async can be controlled per-test."""
    configure = mocker.patch("app.services.llm.gemini.genai.configure")
    model_instance = MagicMock()
    model_cls = mocker.patch(
        "app.services.llm.gemini.genai.GenerativeModel",
        return_value=model_instance,
    )
    return SimpleNamespace(
        configure=configure,
        model_cls=model_cls,
        model_instance=model_instance,
    )


async def test_generate_returns_llm_response_with_all_fields_populated(patched_genai):
    patched_genai.model_instance.generate_content_async = AsyncMock(
        return_value=SimpleNamespace(
            text="hello world",
            usage_metadata=SimpleNamespace(
                prompt_token_count=12,
                candidates_token_count=34,
                total_token_count=46,
            ),
        )
    )

    adapter = GeminiAdapter()
    response = await adapter.generate("hello")

    assert isinstance(response, LLMResponse)
    assert response.content == "hello world"
    assert response.input_tokens == 12
    assert response.output_tokens == 34
    assert response.total_tokens == 46
    assert response.model == "gemini-2.0-flash"
    patched_genai.model_instance.generate_content_async.assert_awaited_once_with("hello")


async def test_generate_handles_missing_usage_metadata(patched_genai):
    # Gemini SDK can return responses where usage_metadata is None or
    # missing (some models, certain error paths). Adapter must default
    # token fields to 0 instead of crashing on AttributeError.
    patched_genai.model_instance.generate_content_async = AsyncMock(
        return_value=SimpleNamespace(text="hello world", usage_metadata=None)
    )

    adapter = GeminiAdapter()
    response = await adapter.generate("hello")

    assert response.content == "hello world"
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.total_tokens == 0
    assert response.model == "gemini-2.0-flash"


def test_build_prompt_is_identity_passthrough(patched_genai):
    adapter = GeminiAdapter()
    assert adapter.build_prompt("hello") == "hello"
    assert adapter.build_prompt("") == ""


async def test_is_healthy_returns_true_on_successful_generate(patched_genai):
    patched_genai.model_instance.generate_content_async = AsyncMock(
        return_value=SimpleNamespace(
            text="pong",
            usage_metadata=SimpleNamespace(
                prompt_token_count=1,
                candidates_token_count=1,
                total_token_count=2,
            ),
        )
    )

    adapter = GeminiAdapter()
    assert await adapter.is_healthy() is True


async def test_is_healthy_returns_false_and_swallows_sdk_exception(patched_genai):
    patched_genai.model_instance.generate_content_async = AsyncMock(
        side_effect=RuntimeError("boom: invalid api key")
    )

    adapter = GeminiAdapter()
    assert await adapter.is_healthy() is False


async def test_generate_propagates_when_response_text_raises(patched_genai, mocker):
    # Gemini's response.text is a @property that raises ValueError when the
    # candidate was blocked (safety filters) or empty. The adapter must let
    # that propagate; is_healthy must still swallow it and return False.
    fake_response = mocker.MagicMock()
    type(fake_response).text = mocker.PropertyMock(side_effect=ValueError("blocked"))
    patched_genai.model_instance.generate_content_async = AsyncMock(return_value=fake_response)

    adapter = GeminiAdapter()

    with pytest.raises(ValueError):
        await adapter.generate("hello")

    assert await adapter.is_healthy() is False
