import os

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

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_metrics_endpoint_exports_http_request_metrics():
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200

    metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "text/plain" in metrics_response.headers["content-type"]
    body = metrics_response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_in_progress" in body
    assert 'path="/"' in body


def test_metrics_group_unmatched_routes_to_control_label_cardinality():
    client = TestClient(app)

    response = client.get("/definitely-not-a-real-route")
    assert response.status_code == 404

    body = client.get("/metrics").text

    assert 'path="__unmatched__"' in body
    assert 'path="/definitely-not-a-real-route"' not in body
