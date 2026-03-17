"""Tests for correlation ID header on all responses."""

from fastapi.testclient import TestClient

import app.main as main_module
from app.database import get_db
from app.main import app
from app.middleware.rate_limit import limiter


def test_correlation_id_on_success(client):
    """Test that correlation ID is included on successful responses."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) == 8  # 4 bytes as hex


def test_correlation_id_on_404_error(client):
    """Test that correlation ID is included on 404 error responses (HTTPException)."""
    response = client.get(
        "/api/v1/secrets/retrieve", headers={"Authorization": "Bearer " + "a" * 64}
    )
    assert response.status_code == 404
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) == 8


def test_correlation_id_on_validation_error(client):
    """Test that correlation ID is included on validation error (422) responses."""
    response = client.post(
        "/api/v1/challenges",
        json={"payload_hash": "tooshort", "ciphertext_size": 100},
    )
    assert response.status_code == 422
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) == 8


def test_correlation_id_on_unauthorized_error(client):
    """Test that correlation ID is included on 401 error responses (HTTPException)."""
    response = client.get("/api/v1/secrets/retrieve", headers={"Authorization": "InvalidFormat"})
    assert response.status_code == 401
    assert "X-Correlation-ID" in response.headers
    assert len(response.headers["X-Correlation-ID"]) == 8


def test_correlation_id_on_unhandled_exception(db_session, monkeypatch):
    """Test that correlation ID is included on 500 responses from unhandled exceptions.

    This test simulates an actual unhandled exception to verify that the custom
    exception handler correctly adds the X-Correlation-ID header to 500 responses.
    """
    from app.routers import secrets

    def raise_error(*args, **kwargs):
        raise RuntimeError("Unexpected database error")

    # Patch the function in the router module
    monkeypatch.setattr(secrets, "get_secret_by_decrypt_token_or_404", raise_error)

    # Setup test client with raise_server_exceptions=False
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    limiter.enabled = False
    original_engine = main_module.engine
    main_module.engine = db_session.get_bind()

    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            response = test_client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": "Bearer " + "a" * 64},
            )

            assert response.status_code == 500
            assert "X-Correlation-ID" in response.headers
            assert len(response.headers["X-Correlation-ID"]) == 8
            assert response.json()["detail"] == "Internal Server Error"
    finally:
        app.dependency_overrides.clear()
        limiter.enabled = True
        main_module.engine = original_engine


def test_correlation_ids_unique_across_requests(client):
    """Test that each request gets a unique correlation ID."""
    response1 = client.get("/health")
    response2 = client.get("/health")

    corr_id_1 = response1.headers.get("X-Correlation-ID")
    corr_id_2 = response2.headers.get("X-Correlation-ID")

    assert corr_id_1 != corr_id_2, "Correlation IDs should be unique across requests"
