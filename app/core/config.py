from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # App
    # ------------------------------------------------------------------
    PROJECT_NAME: str = "anvila-backend"
    API_V1_PREFIX: str = "/api/v1"
    ADMIN_EMAIL: str = "admin@anvila.com"
    ADMIN_PASSWORD: str | None = None
    DATABASE_URL: PostgresDsn
    LOG_LEVEL: str = "INFO"
    FRONTEND_URL: str = "http://localhost:3000"
    TRUSTED_PROXIES: str = ""
    COOKIE_SECURE: bool = True

    # ------------------------------------------------------------------
    # JWT / tokens
    # ------------------------------------------------------------------
    JWT_SECRET: Annotated[str, Field(min_length=32)]
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: Annotated[int, Field(gt=0)] = 60
    REFRESH_TOKEN_EXPIRE_DAYS: Annotated[int, Field(gt=0)] = 7
    VERIFICATION_TOKEN_EXPIRE_HOURS: Annotated[int, Field(gt=0)] = 24
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: Annotated[int, Field(gt=0)] = 60

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------
    BREVO_API_KEY: str = ""
    SMTP_FROM_NAME: str = "Anvila "
    SMTP_FROM_EMAIL: str = "hello@anvila.com"

    # ------------------------------------------------------------------
    # Google OAuth
    # ------------------------------------------------------------------
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    GOOGLE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL: str = "https://openidconnect.googleapis.com/v1/userinfo"
    GOOGLE_SCOPES: str = "openid email profile"

    # ------------------------------------------------------------------
    # GitHub OAuth
    # ------------------------------------------------------------------
    GITHUB_CLIENT_ID: str | None = None
    GITHUB_CLIENT_SECRET: str | None = None
    GITHUB_REDIRECT_URI: str | None = None
    GITHUB_AUTH_URL: str = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
    GITHUB_USERINFO_URL: str = "https://api.github.com/user"
    GITHUB_EMAILS_URL: str = "https://api.github.com/user/emails"
    GITHUB_SCOPES: str = "read:user user:email"
    GITHUB_OAUTH_ENABLED: bool = False
    OAUTH_LINK_TOKEN_EXPIRE_MINUTES: int = 30

    @model_validator(mode="after")
    def _validate_github_oauth_credentials(self) -> "Settings":
        if not self.GITHUB_OAUTH_ENABLED:
            return self
        missing = [
            name
            for name, value in (
                ("GITHUB_CLIENT_ID", self.GITHUB_CLIENT_ID),
                ("GITHUB_CLIENT_SECRET", self.GITHUB_CLIENT_SECRET),
                ("GITHUB_REDIRECT_URI", self.GITHUB_REDIRECT_URI),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "GITHUB_OAUTH_ENABLED=True requires GITHUB_CLIENT_ID, "
                "GITHUB_CLIENT_SECRET, and GITHUB_REDIRECT_URI to be set. "
                f"Missing: {', '.join(missing)}."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "logging.Formatter",
            "fmt": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": settings.LOG_LEVEL,
        },
        "uvicorn.error": {
            "level": "INFO",
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
