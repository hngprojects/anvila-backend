import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import LOGGING_CONFIG, settings

logging.config.dictConfig(LOGGING_CONFIG)  # pyright: ignore[reportAttributeAccessIssue]
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up the FastAPI application...")
    yield
    logger.info("Shutting down the FastAPI application...")


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.PROJECT_NAME} is running"}
