from fastapi import UploadFile


async def extract_text(file: UploadFile) -> str:
    # 1. Read the file content into memory: content = await file.read()
    #
    # 2. Check file.filename extension (lowercase):
    #
    #    .pdf:
    #      Use pdfplumber.open(io.BytesIO(content))
    #      Extract text from each page: page.extract_text() or ""
    #      Join pages with "\n"
    #
    #    .docx:
    #      Use docx2txt.process(io.BytesIO(content))
    #
    #    .txt or .md:
    #      content.decode("utf-8")
    #
    #    anything else:
    #      raise ValueError(f"Unsupported file type: {file.filename}")
    #      The endpoint catches this and returns HTTP 400.
    #
    # 3. Truncate result to 8000 characters.
    #    No flag needed — the generate endpoint just uses whatever is returned.
    #
    # 4. Return the extracted string.
    raise NotImplementedError
