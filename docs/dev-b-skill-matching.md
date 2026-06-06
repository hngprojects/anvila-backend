# Dev B — Skills Module Documentation

## Overview

Dev B is responsible for:

- OpenClaw skill integration
- Skill syncing
- Skill matching
- Public skills API
- Admin skills management

The system uses OpenClaw/ClawHub as the external skill registry and stores fetched skills in the Database.

---

# Public Skills API

## GET `/api/v1/skills`

Returns active skills from the local database.

### Query Params

| Param | Description |
|---|---|
| search | searches name + description |
| category | filters by skill category |
| limit | pagination limit |
| offset | pagination offset |

### Example

```http
GET /api/v1/skills?search=research
```

### Response

```json
{
  "success": true,
  "message": "Skills retrieved successfully",
  "data": [
    {
      "id": "uuid",
      "name": "Research Assistant",
      "slug": "research-assistant",
      "description": "Research helper skill",
      "content": "# Research Assistant",
      "tags": ["research"],
      "source_registry": "openclaw",
      "source_url": "https://...",
      "source_author": "OpenClaw",
      "install_count": 100,
      "is_active": true
    }
  ],
  "meta": {
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

---

# Admin Skills API

All admin endpoints require `AdminUser`.

---

## POST `/api/v1/admin/skills/sync`

Syncs skills from OpenClaw into the local DB.

### Query Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| category | string | No | Filters skills by external registry category |
| limit | integer | No | Limits the number of skills fetched from the external registry |


### Response

```json
{
  "success": true,
  "message": "Skills synced successfully",
  "data": {
    "synced": 5,
    "updated": 2,
    "added": 3
  }
}
```

---

## POST `/api/v1/admin/skills`

Creates a manual Anvila skill.

### Request

```json
{
  "name": "Prompt Refiner",
  "slug": "prompt-refiner",
  "description": "Improves prompts",
  "content": "# Prompt Refiner",
  "category": "development",
  "tags": ["prompting"]
}
```

### Rules

- slug must be unique
- source_registry = ANVILA
- is_active = true

---

## PUT `/api/v1/admin/skills/{slug}`

Updates an existing skill.

### Rules

- slug is immutable
- update only provided fields

---

## DELETE `/api/v1/admin/skills/{slug}`

Soft deletes a skill.

### Behavior

```python
skill.is_active = False
```

Skill remains in DB for existing PersonaSkill references.

---

# OpenClaw Client

## list_openclaw_skills()

Fetches skills from OpenClaw.

### Params

- `limit`
- `nonSuspiciousOnly=true`

### Returns

```python
list[dict]
```

Returns `[]` on failure.

---

## search_openclaw_skills()

Searches OpenClaw skills by text query.

### Returns

```python
list[dict]
```

Returns `[]` on failure.

---

## fetch_openclaw_skill()

Fetches full skill details.

### Returns

```python
dict | None
```

Returns `None` on failure.

---

## fetch_openclaw_skill_markdown()

Fetches `skill.md` content.

### Endpoint

```http
GET /skills/{id}/file?path=skill.md
```

### Returns

```python
str
```

Returns empty string on failure.

---

# Skill Sync

## sync_skills_from_registry()

Fetches OpenClaw skills and stores them locally.

### Flow

1. fetch skills
2. generate slug
3. fetch markdown content
4. check existing skill
5. create or update
6. commit changes
7. return counts

### Return

```json
{
  "synced": 5,
  "updated": 2,
  "added": 3
}
```

---

# Skill Matching

## match_skills()

```python
async def match_skills(
    suggested_slugs: list[str],
    category: str,
    db: AsyncSession,
) -> list[Skill]
```

Used inside persona generation.

### Guarantees

- returns between 2 and 6 skills
- never returns duplicates
- never crashes if OpenClaw fails
- pads with local Anvila skills if fewer than 2 skills found

### Flow

1. normalize slug
2. check local DB
3. if missing → fetch from OpenClaw
4. upsert skill locally
5. add to results
6. if results < 2 → add fallback Anvila skills
7. return max 6 skills

---

# Important Notes

## OpenClaw replaces skills.sh

The project originally referenced `skills.sh` but now uses OpenClaw/ClawHub.

---


## Soft Delete Only

Skills are never physically deleted.

Use:

```python
skill.is_active = False
```

---

# Endpoint Summary

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/skills` | List/search skills |
| POST | `/api/v1/admin/skills/sync` | Sync OpenClaw skills |
| POST | `/api/v1/admin/skills` | Create manual skill |
| PUT | `/api/v1/admin/skills/{slug}` | Update skill |
| DELETE | `/api/v1/admin/skills/{slug}` | Soft delete skill |

---

# Current Status

## Completed

- OpenClaw client
- Skill sync
- Public skills API
- Admin create/update/delete
- Soft delete
- Shared response wrapper
