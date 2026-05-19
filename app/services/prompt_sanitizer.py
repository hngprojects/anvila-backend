import logging
import re

logger = logging.getLogger(__name__)

# Injection patterns to strip from user input.
# Add new patterns here as they are discovered.
# Each pattern is case-insensitive.
INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above)",
    r"you\s+are\s+now\s+",
    r"act\s+as(\s+if\s+you\s+are)?\s+",
    r"pretend\s+to\s+be\s+",
    r"roleplay\s+as\s+",
    r"forget\s+everything",
    r"forget\s+all\s+(you\s+)?(know|were\s+told)",
    r"system\s*:",
    r"<\s*system\s*>",
    r"\[system\]",
    r"\[INST\]",
    r"<<SYS>>",
    r"jailbreak",
    r"\bDAN\b",
    r"do\s+anything\s+now",
    r"override\s+(all\s+)?(safety|rules|guidelines|restrictions)",
    r"reveal\s+(your\s+)?(system\s+prompt|instructions|rules|training)",
    r"prompt\s+injection",
    r"ignore\s+constraints",
]

_BLOCKLIST = re.compile(
    "|".join(INJECTION_PATTERNS),
    re.IGNORECASE,
)

MAX_LENGTH = 4000


class PromptSanitizer:
    def sanitize(self, raw: str) -> str:
        def _replace(match: re.Match[str]) -> str:
            logger.warning("prompt_sanitizer: stripped injection token %r", match.group(0))
            return "[REMOVED]"

        cleaned = _BLOCKLIST.sub(_replace, raw)
        cleaned = re.sub(r"\s{3,}", " ", cleaned)
        cleaned = cleaned.strip()
        cleaned = cleaned[:MAX_LENGTH]

        if not cleaned:
            raise ValueError("Prompt is empty after sanitization.")

        return f"<USER_INPUT>\n{cleaned}\n</USER_INPUT>"
