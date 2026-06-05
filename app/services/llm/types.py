from dataclasses import dataclass


@dataclass
class LLMResponse:
    # The raw text response from the model.
    # Always a string. Never None. May be an empty string if the model
    # returned an empty response (caller should treat this as an error).
    content: str

    # Number of tokens consumed by the prompt sent to the model.
    # Source: response.usage_metadata.prompt_token_count (Gemini)
    input_tokens: int

    # Number of tokens in the model's response.
    # Source: response.usage_metadata.candidates_token_count (Gemini)
    output_tokens: int

    # input_tokens + output_tokens.
    # This is the value persisted to persona.tokens_used
    # and accumulated on user.total_tokens_used.
    total_tokens: int

    # The model identifier string used for this call.
    # Example: "gemini-2.0-flash"
    # Stored for auditability — useful when we support multiple models.
    model: str


@dataclass
class LLMStreamChunk:
    # Incremental text delta from the model. May be "" on the final usage chunk.
    text: str

    # Populated only on the terminal chunk, from provider usage metadata.
    # None on intermediate chunks. Never estimated.
    usage: LLMResponse | None = None
