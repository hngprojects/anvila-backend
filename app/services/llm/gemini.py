from app.services.llm.base import LLMAdapter
from app.services.llm.types import LLMResponse


class GeminiAdapter(LLMAdapter):
    def __init__(self) -> None:
        # Configure the SDK with the API key from settings.
        # Store the model instance on self for reuse.
        # Model name: "gemini-2.0-flash"
        raise NotImplementedError

    def build_prompt(self, prompt: str) -> str:
        raise NotImplementedError

    async def generate(self, prompt: str) -> LLMResponse:
        # Call the Gemini API with prompt
        #
        # Use generate_content_async() for async support.
        # Pass system_prompt as the system instruction and
        # prompt as the user content.
        #
        # Extract token counts from response.usage_metadata:
        #   input_tokens  = usage_metadata.prompt_token_count
        #   output_tokens = usage_metadata.candidates_token_count
        #   total_tokens  = usage_metadata.total_token_count
        #
        # Return LLMResponse with all fields populated.
        # model field = "gemini-2.0-flash"
        raise NotImplementedError

    async def is_healthy(self) -> bool:
        # Attempt a minimal generate() call with a short prompt.
        # Return True if it succeeds.
        # Catch all exceptions and return False — never raise.
        raise NotImplementedError
