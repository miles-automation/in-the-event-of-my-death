def test_health_check(client):
    """Test the health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_healthz_endpoints(client):
    for path in ["/healthz", "/api/v1/healthz"]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
