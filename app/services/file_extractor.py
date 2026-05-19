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

    try:
        if name.endswith(".pdf"):
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        elif name.endswith(".docx"):
            text = docx2txt.process(io.BytesIO(content))
        elif name.endswith((".txt", ".md")):
            text = content.decode("utf-8", errors="replace")
        else:
            raise ValueError(f"Unsupported file type: {file.filename}")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {file.filename}: {exc}") from exc

    return text[:MAX_CHARS]
