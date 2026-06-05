from collections.abc import Iterable
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.llm.gemini import GeminiAdapter
from app.services.llm.types import LLMResponse, LLMStreamChunk

MODEL_NAME = "gemini-2.0-flash"


async def async_chunks(chunks: Iterable[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


@pytest.fixture
def patched_genai(mocker, monkeypatch):
    """Patch google-genai Client so tests do not use a real API key."""
    monkeypatch.setattr(settings, "GEMINI_MODEL_NAME", MODEL_NAME)
    client = mocker.MagicMock()
    client.models.generate_content = mocker.MagicMock()
    client.aio.models.generate_content_stream = mocker.AsyncMock()
    client_cls = mocker.patch("app.services.llm.gemini.genai.Client", return_value=client)
    return SimpleNamespace(client_cls=client_cls, client=client)


async def test_generate_returns_llm_response_with_all_fields_populated(patched_genai):
    patched_genai.client.models.generate_content.return_value = SimpleNamespace(
        text='{"message": "hello world"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=34,
            total_token_count=46,
        ),
    )

    adapter = GeminiAdapter()
    response = await adapter.generate("hello")

    assert isinstance(response, LLMResponse)
    assert response.content == '{"message": "hello world"}'
    assert response.input_tokens == 12
    assert response.output_tokens == 34
    assert response.total_tokens == 46
    assert response.model == MODEL_NAME
    patched_genai.client.models.generate_content.assert_called_once_with(
        model=MODEL_NAME,
        contents="hello",
    )


async def test_generate_handles_missing_usage_metadata(patched_genai):
    # Gemini SDK can return responses where usage_metadata is None or
    # missing. Adapter must default token fields to 0 instead of crashing.
    patched_genai.client.models.generate_content.return_value = SimpleNamespace(
        text='{"message": "hello world"}',
        usage_metadata=None,
    )

    adapter = GeminiAdapter()
    response = await adapter.generate("hello")

    assert response.content == '{"message": "hello world"}'
    assert response.input_tokens == 0
    assert response.output_tokens == 0
    assert response.total_tokens == 0
    assert response.model == MODEL_NAME


def test_build_prompt_is_identity_passthrough(patched_genai):
    adapter = GeminiAdapter()
    assert adapter.build_prompt("hello") == "hello"
    assert adapter.build_prompt("") == ""


async def test_is_healthy_returns_true_on_successful_generate(patched_genai):
    patched_genai.client.models.generate_content.return_value = SimpleNamespace(
        text='{"status": "pong"}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=1,
            candidates_token_count=1,
            total_token_count=2,
        ),
    )

    adapter = GeminiAdapter()
    assert await adapter.is_healthy() is True


async def test_is_healthy_returns_false_and_swallows_sdk_exception(patched_genai):
    patched_genai.client.models.generate_content.side_effect = RuntimeError("boom: invalid api key")

    adapter = GeminiAdapter()
    assert await adapter.is_healthy() is False


async def test_generate_propagates_when_response_text_raises(patched_genai, mocker):
    # Gemini's response.text property raises ValueError when the candidate was
    # blocked or empty. The adapter must let that propagate; is_healthy must
    # still swallow it and return False.
    fake_response = mocker.MagicMock()
    type(fake_response).text = mocker.PropertyMock(side_effect=ValueError("blocked"))
    patched_genai.client.models.generate_content.return_value = fake_response

    adapter = GeminiAdapter()

    with pytest.raises(ValueError):
        await adapter.generate("hello")

    assert await adapter.is_healthy() is False


async def test_stream_yields_text_deltas_then_usage(patched_genai):
    patched_genai.client.aio.models.generate_content_stream.return_value = async_chunks(
        [
            SimpleNamespace(text="hello", usage_metadata=None),
            SimpleNamespace(text=" world", usage_metadata=None),
            SimpleNamespace(
                text="!",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=12,
                    candidates_token_count=34,
                    total_token_count=46,
                ),
            ),
        ]
    )

    adapter = GeminiAdapter()
    chunks = [chunk async for chunk in adapter.stream("hello")]

    assert [chunk.text for chunk in chunks] == ["hello", " world", "!", ""]
    assert all(isinstance(chunk, LLMStreamChunk) for chunk in chunks)
    assert chunks[-1].usage == LLMResponse(
        content="",
        input_tokens=12,
        output_tokens=34,
        total_tokens=46,
        model=MODEL_NAME,
    )
    patched_genai.client.aio.models.generate_content_stream.assert_awaited_once_with(
        model=MODEL_NAME,
        contents="hello",
    )


async def test_stream_skips_empty_text_chunks(patched_genai):
    patched_genai.client.aio.models.generate_content_stream.return_value = async_chunks(
        [
            SimpleNamespace(text="first", usage_metadata=None),
            SimpleNamespace(text="", usage_metadata=None),
            SimpleNamespace(text=None, usage_metadata=None),
            SimpleNamespace(text="last", usage_metadata=None),
        ]
    )

    adapter = GeminiAdapter()
    chunks = [chunk async for chunk in adapter.stream("hello")]

    assert [chunk.text for chunk in chunks] == ["first", "last", ""]
    assert chunks[-1].usage == LLMResponse(
        content="",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        model=MODEL_NAME,
    )


async def test_stream_defaults_usage_to_zero_when_metadata_missing(patched_genai):
    patched_genai.client.aio.models.generate_content_stream.return_value = async_chunks(
        [
            SimpleNamespace(text="hello", usage_metadata=None),
            SimpleNamespace(text=" world", usage_metadata=None),
        ]
    )

    adapter = GeminiAdapter()
    chunks = [chunk async for chunk in adapter.stream("hello")]

    assert [chunk.text for chunk in chunks] == ["hello", " world", ""]
    assert chunks[-1].usage == LLMResponse(
        content="",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        model=MODEL_NAME,
    )
