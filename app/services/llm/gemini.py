import asyncio
import logging
from collections.abc import AsyncIterator

from google import genai
from google.genai.errors import APIError, ClientError

from app.core.config import settings
from app.services.llm.base import LLMAdapter
from app.services.llm.key_manager import AllKeysExhaustedError, GeminiKeyManager
from app.services.llm.types import LLMResponse
from app.services.llm.types import LLMResponse, LLMStreamChunk
from app.services.llm.utils import extract_json

logger = logging.getLogger(__name__)


def _is_quota_error(exc: Exception) -> bool:
    """Return True only for HTTP 429 — quota / rate-limit exhaustion."""
    return isinstance(exc, ClientError) and exc.code == 429


class GeminiAdapter(LLMAdapter):
    """
    Gemini LLM adapter with transparent key rotation.

    A single GeminiKeyManager is shared at the class level so every adapter
    instance (and every concurrent request) sees the same key state.
    """

    _key_manager: GeminiKeyManager | None = None

    @classmethod
    def _get_key_manager(cls) -> GeminiKeyManager:
        if cls._key_manager is None:
            raw_keys: list[str] = getattr(settings, "GEMINI_API_KEYS", None) or []
            if not raw_keys and getattr(settings, "GEMINI_API_KEY", None):
                raw_keys = [settings.GEMINI_API_KEY]  # type: ignore

            cls._key_manager = GeminiKeyManager(
                keys=raw_keys,
            )
        return cls._key_manager

    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._manager = self._get_key_manager()
        self._model_name: str = settings.GEMINI_MODEL_NAME
        self._client = self._build_client()

    def _build_client(self) -> genai.Client:
        return genai.Client(api_key=self._manager.current_key)

    def build_prompt(self, prompt: str) -> str:
        return prompt

    async def generate(self, prompt: str) -> LLMResponse:
        exhausted_key = self._manager.current_key
        try:
            return await self._call(prompt)
        except APIError as exc:
            if not _is_quota_error(exc):
                logger.error(
                    "Gemini API error on %s (code=%s status=%s): %s",
                    self._manager.active_key_label,
                    exc.code,
                    exc.status,
                    exc.message,
                )
                raise

            logger.warning(
                "Quota exhausted on %s (429) — rotating key.",
                self._manager.active_key_label,
            )
            try:
                await self._manager.rotate(exhausted_key=exhausted_key)
            except AllKeysExhaustedError:
                logger.error("All Gemini API keys are exhausted.")
                raise

            self._client = self._build_client()
            logger.info("Retrying with %s.", self._manager.active_key_label)
            return await self._call(prompt)

    async def _call(self, prompt: str) -> LLMResponse:
        response = await asyncio.to_thread(
            self._client.models.generate_content,
            model=self._model_name,
            contents=prompt,
        )
        usage = getattr(response, "usage_metadata", None)
        content = extract_json(response.text or "")
        return LLMResponse(
            content=content,
            input_tokens=getattr(usage, "prompt_token_count", 0),
            output_tokens=getattr(usage, "candidates_token_count", 0),
            total_tokens=getattr(usage, "total_token_count", 0),
            model=self._model_name,
        )

    async def stream(self, prompt: str) -> AsyncIterator[LLMStreamChunk]:
        last_usage = None
        stream = await self.client.aio.models.generate_content_stream(
            model=self._model_name,
            contents=prompt,
        )

        async for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                last_usage = usage

            text = getattr(chunk, "text", None) or ""
            if text:
                yield LLMStreamChunk(text=text)

        yield LLMStreamChunk(
            text="",
            usage=LLMResponse(
                content="",
                input_tokens=getattr(last_usage, "prompt_token_count", 0),
                output_tokens=getattr(last_usage, "candidates_token_count", 0),
                total_tokens=getattr(last_usage, "total_token_count", 0),
                model=self._model_name,
            ),
        )

    async def is_healthy(self) -> bool:
        try:
            await self.generate("ping")
            return True
        except Exception:
            return False

    def key_status(self) -> list[dict]:
        return self._manager.status()
