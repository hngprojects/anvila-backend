import os

# Provide required env vars before app.core.security is imported during collection.
# JWT tests don't use the DB; DATABASE_URL satisfies pydantic-settings validation only.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "placeholder-overridden-by-patch-settings-fixture")
