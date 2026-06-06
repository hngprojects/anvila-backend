from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.services.llm.types import LLMResponse, LLMStreamChunk


class LLMAdapter(ABC):
    @abstractmethod
    def build_prompt(self, prompt: str) -> str:
        # Builds the final prompt by injecting user prompt into a template
        # that includes the system prompt and any other required context.
        ...

    @abstractmethod
    async def generate(self, prompt: str) -> LLMResponse:
        # Generate a response from the LLM.
        #
        # `prompt` is required. It will be passed to `build_prompt()` which
        # injects it into a larger prompt template that includes the system
        # prompt and any other required context.
        #
        # The `prompt` argument is the user-facing content (already sanitized
        # and wrapped by PromptSanitizer before this call).
        #
        # Returns a fully populated LLMResponse.
        # Token fields must always be populated from the provider's
        # usage metadata — never hardcoded or estimated.
        #
        # Raises on API failure (httpx.HTTPError or provider SDK error).
        # Caller is responsible for catching and handling the exception.
        ...

    @abstractmethod
    def stream(self, prompt: str) -> AsyncIterator[LLMStreamChunk]:
        # Stream the model response as incremental text deltas.
        #
        # Yields LLMStreamChunk(text=...) for each text delta, then a final
        # chunk with usage populated from provider metadata.
        #
        # `prompt` is already sanitized/wrapped by the caller, same as
        # generate().
        #
        # Raises on API failure. Caller handles exceptions.
        ...

    @abstractmethod
    async def is_healthy(self) -> bool:
        # Check whether the provider is reachable and the API key is valid.
        #
        # Must never raise — catch all exceptions internally and return False.
        # Used on app startup and by the health check endpoint.
        #
        # Returns True if the provider is ready to accept generate() calls.
        # Returns False on any error (network, auth, timeout, etc.).
        ...
