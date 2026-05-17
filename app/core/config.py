from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn
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
    ADMIN_EMAIL: str | None = None
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
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str
    GITHUB_REDIRECT_URI: str
    GITHUB_AUTH_URL: str = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
    GITHUB_USERINFO_URL: str = "https://api.github.com/user"
    GITHUB_EMAILS_URL: str = "https://api.github.com/user/emails"
    GITHUB_SCOPES: str = "read:user user:email"
    GITHUB_OAUTH_ENABLED: bool = False
    OAUTH_LINK_TOKEN_EXPIRE_MINUTES: int = 30


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
