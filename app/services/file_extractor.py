import asyncio
import io

import docx2txt
import pdfplumber
from fastapi import UploadFile

MAX_CHARS = 8000
MAX_FILE_BYTES = 5 * 1024 * 1024


async def extract_text(file: UploadFile) -> str:
    content = await file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"File too large (max {MAX_FILE_BYTES} bytes).")
    name = (file.filename or "").lower()

    def _parse_sync() -> str:
        if name.endswith(".pdf"):
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        if name.endswith(".docx"):
            return docx2txt.process(io.BytesIO(content))
        if name.endswith((".txt", ".md")):
            return content.decode("utf-8", errors="replace")
        raise ValueError(f"Unsupported file type: {file.filename}")

    try:
        text = await asyncio.to_thread(_parse_sync)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {file.filename}: {exc}") from exc

    return text[:MAX_CHARS]
