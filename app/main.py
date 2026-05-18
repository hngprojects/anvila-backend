import logging
import logging.config
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

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

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the Anvila API.",
    ["method", "path", "status"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds for the Anvila API.",
    ["method", "path", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being processed by the Anvila API.",
    ["method", "path"],
)


def _route_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    method = request.method
    in_progress_path = request.url.path
    path = in_progress_path
    start = time.perf_counter()
    status = "500"

    HTTP_REQUESTS_IN_PROGRESS.labels(method=method, path=in_progress_path).inc()
    try:
        response = await call_next(request)
        status = str(response.status_code)
        path = _route_path(request)
        return response
    finally:
        duration = time.perf_counter() - start
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, path=in_progress_path).dec()
        HTTP_REQUESTS_TOTAL.labels(method=method, path=path, status=status).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            path=path,
            status=status,
        ).observe(duration)


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.PROJECT_NAME} is running"}
