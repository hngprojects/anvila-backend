# Anvila — Stub Implementation Guidelines

This document is the companion to the stub files. Read it before you write a
single line of implementation. It tells you what each stub expects, what the
contracts are between stubs, and what "done" looks like for each one.

---

## How the stub system works

Every stub file has the correct function signature and a docstring or inline
comments describing exactly what the implementation must do. The body raises
`NotImplementedError`. Your job is to replace `raise NotImplementedError` with
a real implementation that satisfies everything described in the comments.

**Do not change signatures.** The function name, parameters, and return type
are frozen. Other engineers are importing and calling these right now. Changing
a signature mid-sprint breaks everyone who depends on it.

**Imports go inside functions in Celery tasks.** To avoid circular imports
with the Celery worker process, all imports in `generation.py` and `cleanup.py`
go inside the function body, not at the top of the file.

---

## File-by-file guidelines

---

### `app/services/llm/types.py` — LLMResponse

**Owner:** Dev A  
**Status:** Already complete — no implementation needed. It is a dataclass.  
**Action:** Copy this file into the project. No changes required.

---

### `app/services/llm/base.py` — LLMAdapter

**Owner:** Dev A  
**Status:** Already complete — abstract class only. No implementation needed.  
**Action:** Copy this file into the project. No changes required.

---

### `app/services/llm/gemini.py` — GeminiAdapter

**Owner:** Dev A

**What to install:**
```
uv add google-generativeai
```

**What to implement:**

`__init__`:
- Call `genai.configure(api_key=settings.GEMINI_API_KEY)`
- Instantiate the model: `self.model = genai.GenerativeModel("gemini-2.0-flash")`
- Store model name on `self._model_name = "gemini-2.0-flash"` for the response

`generate`:
- Call `await self.model.generate_content_async([prompt])`
- Extract text: `response.text`
- Extract tokens from `response.usage_metadata`:
  - `input_tokens = response.usage_metadata.prompt_token_count`
  - `output_tokens = response.usage_metadata.candidates_token_count`
  - `total_tokens = response.usage_metadata.total_token_count`
- Return `LLMResponse(content=..., input_tokens=..., output_tokens=..., total_tokens=..., model=self._model_name)`

`is_healthy`:
```python
try:
    await self.generate("ping")
    return True
except Exception:
    return False
```

**Done when:**
- `adapter.generate("hello")` returns an `LLMResponse` with non-zero tokens
- `adapter.is_healthy()` returns `True` with a valid key, `False` with an invalid key

---

### `app/llm/factory.py` — get_llm_adapter

**Owner:** Dev A

**What to implement:**
```python
from app.core.config import settings
from app.llm.gemini import GeminiAdapter

def get_llm_adapter() -> LLMAdapter:
    if settings.LLM_PROVIDER == "gemini":
        return GeminiAdapter()
    raise ValueError(f"Unsupported LLM provider: {settings.LLM_PROVIDER}")
```

**Done when:**
- `get_llm_adapter()` returns a `GeminiAdapter` when `LLM_PROVIDER=gemini`
- Raises `ValueError` for any other string

---

### `app/services/prompt_sanitizer.py` — PromptSanitizer

**Owner:** Dev A

**What to implement in `sanitize`:**

```python
import re
import logging

logger = logging.getLogger(__name__)

def sanitize(self, raw: str) -> str:
    # Step 1: blocklist
    def replace_match(m):
        logger.warning(f"Injection pattern detected: {m.group()!r}")
        return "[REMOVED]"
    
    cleaned = _BLOCKLIST.sub(replace_match, raw)
    
    # Step 2: collapse whitespace
    cleaned = re.sub(r"\s{3,}", " ", cleaned)
    
    # Step 3: strip
    cleaned = cleaned.strip()
    
    # Step 4: truncate
    cleaned = cleaned[:MAX_LENGTH]
    
    # Step 5: check empty
    if not cleaned:
        raise ValueError("Prompt is empty after sanitization.")
    
    # Step 6: wrap
    return f"<USER_INPUT>\n{cleaned}\n</USER_INPUT>"
```

**Done when:**
- Each pattern in `INJECTION_PATTERNS` is correctly stripped in isolation
- Empty-after-sanitization raises `ValueError`
- Output always contains `<USER_INPUT>` wrapper
- Text over 4000 chars is truncated before wrapping

---

### `app/services/context_manager.py` — ContextManager

**Owner:** Dev A

**`compress` — what to implement:**

```python
async def compress(self, session, new_answers, db):
    # Format answers
    qa_lines = "\n".join(
        f"Q: {a['id']}\nA: {a['answer']}" for a in new_answers
    )
    new_block = f"Round {session.clarification_round} answers:\n{qa_lines}"
    
    if session.compressed_context:
        updated = f"{session.compressed_context}\n\n{new_block}"
    else:
        updated = f"User intent:\n{new_block}"
    
    session.compressed_context = updated
    await db.commit()
    return updated
```

**`build_followup_prompt` — what to implement:**

```python
def build_followup_prompt(self, session, answers, system_prompt):
    answers_text = "\n".join(
        f"- {a['id']}: {a['answer']}" for a in answers
    )
    return (
        f"{system_prompt}\n\n"
        f"---\n\n"
        f"CONTEXT SO FAR:\n{session.compressed_context or 'None'}\n\n"
        f"---\n\n"
        f"LATEST ANSWERS:\n{answers_text}\n\n"
        f"Continue generation or ask further questions if still unclear."
    )
```

**Done when:**
- Each call to `compress` appends to the context without re-sending history
- `build_followup_prompt` never includes raw message history — only the summary

---

### `app/services/skill_matcher.py` — match_skills

**Owner:** Dev B

**Dependencies:**
```
uv add httpx
```

**What to implement:**

```python
import httpx
from app.core.config import settings
from app.models.enums import SkillSourceRegistry, PersonaCategory
from sqlalchemy import select

async def match_skills(suggested_slugs, category, db):
    results = []
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for slug in suggested_slugs:
            try:
                r = await client.get(f"{settings.SKILLSH_API_BASE}/skills/{slug}")
                if r.status_code == 200:
                    data = r.json()
                    # upsert into local skills table
                    skill = await _upsert_skill(data, db)
                    results.append(skill)
                    continue
            except Exception:
                pass
            
            # fallback: local DB
            result = await db.execute(
                select(Skill).where(Skill.slug == slug, Skill.is_active == True)
            )
            local = result.scalar_one_or_none()
            if local:
                results.append(local)
    
    # pad to minimum 2
    if len(results) < 2:
        needed = 2 - len(results)
        existing_ids = {s.id for s in results}
        result = await db.execute(
            select(Skill)
            .where(
                Skill.category == category,
                Skill.is_active == True,
                Skill.source_registry == SkillSourceRegistry.ANVILA,
                Skill.id.notin_(existing_ids),
            )
            .limit(needed)
        )
        results.extend(result.scalars().all())
    
    return results[:6]  # cap at 6
```

**Done when:**
- Returns 2-6 `Skill` objects under all conditions
- Does not raise when skills.sh is unreachable
- Does not raise when a slug is not found locally

---

### `app/services/skill_sync.py` — sync_skills_from_registry

**Owner:** Dev B

**What to implement:**

```python
import httpx
import logging
from app.core.config import settings
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

async def sync_skills_from_registry() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{settings.SKILLSH_API_BASE}/skills")
            r.raise_for_status()
            skills_data = r.json()
    except Exception as e:
        logger.warning(f"skills.sh unreachable: {e}")
        return {"synced": 0, "updated": 0, "added": 0}
    
    added = updated = 0
    async with AsyncSessionLocal() as db:
        for item in skills_data:
            was_added = await _upsert_skill(item, db)
            if was_added:
                added += 1
            else:
                updated += 1
        await db.commit()
    
    return {"synced": added + updated, "updated": updated, "added": added}
```

Write a private `_upsert_skill` helper that checks if the slug exists and
inserts or updates accordingly.

**Done when:**
- Running with skills.sh reachable populates the local skills table
- Running with skills.sh unreachable returns zeros and does not raise
- Running twice produces no duplicates

---

### `app/services/readme_builder.py` — build_readme

**Owner:** Dev A

**What to implement:**

```python
from datetime import datetime, timezone

def build_readme(persona_data: dict, skills: list) -> str:
    name = persona_data.get("name", "Unnamed Persona")
    category = persona_data.get("category", "")
    description = persona_data.get("description_summary", "")
    
    skill_lines = "\n".join(
        f"- **{s.name}** — {s.description}" for s in skills
    ) or "_No skills attached._"
    
    return f"""# {name}

> {description}

**Category:** {category}

## Persona Files
- [Identity](./identity.md)
- [Soul](./soul.md)
- [DNA](./dna.md)
- [Overview](./overview.md)
- [Heartbeat](./heartbeat.md)

## Skills
{skill_lines}

---
_Generated by Anvila_
"""
```

**Done when:**
- Returns a valid Markdown string for any non-empty `persona_data`
- Skill list renders one line per skill
- Works with an empty skills list (shows fallback text)

---

### `app/services/file_extractor.py` — extract_text

**Owner:** Dev D

**What to install:**
```
uv add pdfplumber docx2txt
```

**What to implement:**

```python
import io
import pdfplumber
import docx2txt
from fastapi import UploadFile

MAX_CHARS = 8000

async def extract_text(file: UploadFile) -> str:
    content = await file.read()
    name = (file.filename or "").lower()
    
    if name.endswith(".pdf"):
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    elif name.endswith(".docx"):
        text = docx2txt.process(io.BytesIO(content))
    elif name.endswith((".txt", ".md")):
        text = content.decode("utf-8")
    else:
        raise ValueError(f"Unsupported file type: {file.filename}")
    
    return text[:MAX_CHARS]
```

**Done when:**
- Each file type extracts correctly
- Output never exceeds 8000 chars
- Unsupported extension raises `ValueError`
- Nothing is written to disk

---

### `app/worker/celery_app.py`

**Owner:** Dev D  
**Status:** Already complete — no `raise NotImplementedError` in this file.  
**Action:** Copy into the project. Add `REDIS_URL` to `settings`.

---

### `app/worker/tasks/generation.py` — generate_persona

**Owner:** Dev A

This is the most complex stub. Full step-by-step in the sprint plan.
Key things to decide before implementing:

1. **Sync vs async inside Celery.** Celery tasks are sync by default.
   Use `asyncio.run(your_async_fn())` to call async code, or use a
   sync SQLAlchemy session. Pick one approach and stick to it.

2. **Redis pub/sub for clarification wait.** The task publishes a
   clarification event and then needs to wait for the clarify endpoint
   to signal it to continue. Use Redis pub/sub:
   ```python
   import redis
   r = redis.from_url(settings.REDIS_URL)
   pubsub = r.pubsub()
   pubsub.subscribe(f"persona:{persona_id}:continue")
   # block waiting for message with a timeout
   for message in pubsub.listen():
       if message["type"] == "message":
           break  # got the continue signal
   ```
   The clarify endpoint publishes to this channel after updating context.

3. **Token accumulation.** Each LLM call (including multiple clarification
   rounds) adds to `persona.tokens_used` and `user.total_tokens_used`.
   Do not reset — always add to the existing value.

**Done when:**
- A persona record transitions through all statuses correctly
- Files are saved individually (not all at once)
- Token counts are persisted after every LLM call
- Failed task preserves any files already saved

---

### `app/worker/tasks/cleanup.py` — purge_soft_deleted

**Owner:** Dev D

Use bulk delete, not row-by-row:
```python
from sqlalchemy import delete, and_
from datetime import datetime, timedelta, timezone

cutoff = datetime.now(timezone.utc) - timedelta(days=30)

# Step 1: messages (FK child of sessions)
await db.execute(
    delete(ConversationMessage).where(
        ConversationMessage.session_id.in_(
            select(ChatSession.id).where(ChatSession.deleted_at < cutoff)
        )
    )
)

# Step 2: sessions
await db.execute(
    delete(ChatSession).where(ChatSession.deleted_at < cutoff)
)

# Step 3: personas
await db.execute(
    delete(Persona).where(Persona.deleted_at < cutoff)
)

await db.commit()
```

---

### `app/api/deps.py` — permission dependencies

**Owner:** Dev D

Replace each `raise NotImplementedError` with the logic described in the
inline comments. The pattern is identical for all four:

```python
from fastapi import HTTPException
from app.models.enums import UserPlan

def require_can_generate(user: CurrentUser) -> User:
    if user.plan == UserPlan.FREE and user.generation_count >= 3:
        raise HTTPException(
            status_code=403,
            detail={"code": "GENERATION_LIMIT_REACHED",
                    "message": "Free plan limit of 3 personas reached."}
        )
    return user
```

Follow this exact pattern for the other three. Use the correct field and
threshold for each as described in the stub comments.

**Done when:**
- Each dep raises the correct error code at exactly the right condition
- Each dep returns the user object on success
- The `Annotated` aliases are importable and work as FastAPI deps

---

## Shared contracts (do not change)

These are agreed between devs. Changing any of these mid-sprint breaks
the engineer who depends on them.

| Contract | Agreed value |
|---|---|
| Redis channel key (clarification events) | `f"persona:{persona_id}:events"` |
| Redis channel key (continue signal) | `f"persona:{persona_id}:continue"` |
| `match_skills` signature | `(suggested_slugs: list[str], category: str, db: AsyncSession) -> list[Skill]` |
| `build_readme` signature | `(persona_data: dict, skills: list[Skill]) -> str` |
| `PromptSanitizer.sanitize` signature | `(raw: str) -> str` — raises `ValueError` on empty |
| `LLMResponse` fields | `content, input_tokens, output_tokens, total_tokens, model` — all required |
| `extract_text` signature | `(file: UploadFile) -> str` — raises `ValueError` on unsupported type |

---

## Quick import reference

```python
from app.llm.types                 import LLMResponse
from app.llm.base                  import LLMAdapter
from app.llm.factory               import get_llm_adapter
from app.services.prompt_sanitizer import PromptSanitizer
from app.services.context_manager  import ContextManager
from app.services.skill_matcher    import match_skills
from app.services.skill_sync       import sync_skills_from_registry
from app.services.readme_builder   import build_readme
from app.services.file_extractor   import extract_text
from app.worker.celery_app         import celery_app
from app.worker.tasks.generation   import generate_persona
from app.api.deps                  import CanGenerate, CanRefine, ProUser, AdminUser
```

---

## Definition of done per stub

| Stub | Done when |
|---|---|
| `GeminiAdapter` | `generate()` returns `LLMResponse` with non-zero tokens on real API call |
| `get_llm_adapter` | Returns `GeminiAdapter` for `gemini`, raises `ValueError` otherwise |
| `PromptSanitizer.sanitize` | Strips all blocklist patterns, wraps output, raises on empty |
| `ContextManager.compress` | Appends to context without duplicating history, saves to DB |
| `ContextManager.build_followup_prompt` | Returns string with system prompt + context + answers |
| `match_skills` | Returns 2-6 skills under all conditions including skills.sh down |
| `sync_skills_from_registry` | Upserts skills, returns zero counts (not an error) when unreachable |
| `build_readme` | Returns valid Markdown string for any persona data + skill list |
| `extract_text` | Extracts all 4 file types in-memory, truncates at 8000, raises on unsupported |
| `generate_persona` | Persona transitions all statuses, files saved individually, tokens recorded |
| `purge_soft_deleted` | Bulk-deletes records older than 30 days in correct FK order |
| Permission deps | Each raises correct error code at exact boundary condition |
