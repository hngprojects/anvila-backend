import re

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


class PromptSanitiser:
    def sanitize(self, raw: str) -> str:
        # Step 1: Run blocklist regex.
        #   Replace each matched segment with "[REMOVED]".
        #   Log each violation (use the app logger, not print).
        #
        # Step 2: Collapse 3+ consecutive whitespace characters to one space.
        #
        # Step 3: Strip leading/trailing whitespace.
        #
        # Step 4: Truncate to MAX_LENGTH characters.
        #
        # Step 5: Wrap in structural delimiter:
        #   return f"<USER_INPUT>\n{sanitized}\n</USER_INPUT>"
        #
        # Step 6: If the sanitized text (before wrapping) is empty,
        #   raise ValueError("Prompt is empty after sanitization.")
        #   The endpoint catches this and returns HTTP 422.
        raise NotImplementedError
