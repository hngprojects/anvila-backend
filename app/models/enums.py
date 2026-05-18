import enum


class UserProvider(enum.StrEnum):
    EMAIL = "email"
    GOOGLE = "google"
    GITHUB = "github"


class UserPlan(enum.StrEnum):
    FREE = "free"
    PAID = "paid"


class PersonaCategory(enum.StrEnum):
    MARKETING = "marketing"
    DEVELOPMENT = "development"
    RESEARCH = "research"
    FINANCE = "finance"


class PersonaVisibility(enum.StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class PersonaStatus(enum.StrEnum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class SkillSourceRegistry(enum.StrEnum):
    SKILLS_SH = "skills.sh"
    OPENCLAW = "openclaw"
    ANVILA = "anvila"


class SessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
