import io

import docx2txt
import pdfplumber
from fastapi import UploadFile

MAX_CHARS = 8000


async def extract_text(file: UploadFile) -> str:
    content = await file.read()
    name = (file.filename or "").lower()

    if name.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    elif name.endswith(".docx"):
        text = docx2txt.process(io.BytesIO(content))
    elif name.endswith((".txt", ".md")):
        text = content.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {file.filename}")

    return text[:MAX_CHARS]
