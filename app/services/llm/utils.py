import json
import re


def extract_json(text: str) -> str:
    """
    Strip markdown fences and extract raw JSON.
    Handles ```json ... ``` and ``` ... ``` wrappers.
    Raises ValueError if no valid JSON object or array can be found.
    """
    text = text.strip()

    fenced = re.match(r"^```(?:json)?\s*\n(.*?)\n```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Gemini response is not valid JSON after stripping fences: {exc}"
        ) from exc

    return text
