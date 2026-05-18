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
    SALES = "sales"
    DEVOPS = "devops"
    SUPPORT = "support"
    ENGINEERING = "engineering"
    HR = "hr"
    LEGAL = "legal"
    PRODUCT = "product"
    DESIGN = "design"


class PersonaVisibility(enum.StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class PersonaStatus(enum.StrEnum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    GENERATING = "generating"
    SKILLS_MATCHING = "skills_matching"
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
