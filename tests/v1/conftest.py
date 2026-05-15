import os

# Required before any app.core.config import during collection.
# pydantic-settings validates DATABASE_URL at instantiation time even in unit tests.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
