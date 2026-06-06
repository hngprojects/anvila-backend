import os

# These setdefaults MUST run before any test module imports app.core.config.
# Settings() is instantiated and cached at app.core.config module import time,
# so any env var that affects Settings (validator gates, default values) must
# be present in os.environ before that import — otherwise the cached settings
# diverge from what the conftests under tests/v1/ later set, and tests that
# depend on those fields (e.g. GITHUB_OAUTH_ENABLED gating the GitHub auth
# routes) fail in full-suite runs while passing in isolation.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://anvila_test:anvila_test_pass@localhost:5432/anvila_backend_test",
)
os.environ.setdefault("JWT_SECRET", "ci-test-secret-key-minimum-32-characters-long")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
os.environ.setdefault(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/google/callback",
)
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "test-github-client-secret")
os.environ.setdefault(
    "GITHUB_REDIRECT_URI",
    "http://localhost:8000/api/v1/auth/github/callback",
)
os.environ.setdefault("GITHUB_OAUTH_ENABLED", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GEMINI_API_KEY", "test-placeholder-key")
