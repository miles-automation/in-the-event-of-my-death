"""Tests for the vault sync API."""

import base64
import hashlib
import secrets


def make_vault_id():
    """Generate a valid vault_id (SHA-256 hex digest)."""
    return hashlib.sha256(secrets.token_bytes(32)).hexdigest()


def make_sync_token():
    """Generate a random sync token (hex)."""
    return secrets.token_hex(32)


def make_ciphertext_b64(size=128):
    """Generate random base64-encoded ciphertext."""
    return base64.b64encode(secrets.token_bytes(size)).decode()


class TestVaultBootstrap:
    """Tests for creating a new vault (PUT with If-None-Match: *)."""

    def test_create_vault(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["created"] is True
        assert "etag" in data
        assert response.headers.get("ETag") is not None

    def test_create_vault_duplicate(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # First create
        client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        # Second create with same vault_id
        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        assert response.status_code == 412
        assert "already exists" in response.json()["detail"]

    def test_create_vault_invalid_vault_id(self, client):
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        response = client.put(
            "/api/v1/vault/not-a-valid-hex",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        assert response.status_code == 400
        assert "Invalid vault_id" in response.json()["detail"]


class TestVaultGet:
    """Tests for fetching a vault blob (GET)."""

    def test_get_vault_success(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        create_resp = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )
        assert create_resp.status_code == 201

        # Fetch
        response = client.get(
            f"/api/v1/vault/{vault_id}",
            headers={"Authorization": f"Bearer {sync_token}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ciphertext"] == ciphertext
        assert "etag" in data
        assert response.headers.get("ETag") is not None

    def test_get_vault_wrong_token(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        wrong_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        # Fetch with wrong token — should return 404, not 401
        response = client.get(
            f"/api/v1/vault/{vault_id}",
            headers={"Authorization": f"Bearer {wrong_token}"},
        )

        assert response.status_code == 404

    def test_get_vault_nonexistent(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()

        response = client.get(
            f"/api/v1/vault/{vault_id}",
            headers={"Authorization": f"Bearer {sync_token}"},
        )

        assert response.status_code == 404


class TestVaultUpdate:
    """Tests for updating a vault blob (PUT with If-Match)."""

    def test_update_vault_etag_match(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        create_resp = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )
        etag = create_resp.json()["etag"]

        # Update with matching ETag
        new_ciphertext = make_ciphertext_b64(256)
        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": new_ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-Match": f'"{etag}"',
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] is False
        assert data["etag"] != etag  # New ETag generated

        # Verify new ciphertext is stored
        get_resp = client.get(
            f"/api/v1/vault/{vault_id}",
            headers={"Authorization": f"Bearer {sync_token}"},
        )
        assert get_resp.json()["ciphertext"] == new_ciphertext

    def test_update_vault_etag_mismatch(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        # Update with stale ETag
        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": make_ciphertext_b64()},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-Match": '"stale-etag-value"',
            },
        )

        assert response.status_code == 409
        assert "ETag mismatch" in response.json()["detail"]

    def test_update_vault_missing_concurrency_header(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        # Update without If-Match or If-None-Match
        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": make_ciphertext_b64()},
            headers={"Authorization": f"Bearer {sync_token}"},
        )

        assert response.status_code == 428

    def test_update_vault_wrong_token(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        wrong_token = make_sync_token()
        ciphertext = make_ciphertext_b64()

        # Create
        create_resp = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": ciphertext},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )
        etag = create_resp.json()["etag"]

        # Update with wrong syncToken
        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": make_ciphertext_b64()},
            headers={
                "Authorization": f"Bearer {wrong_token}",
                "If-Match": f'"{etag}"',
            },
        )

        assert response.status_code == 404


class TestVaultSizeLimit:
    """Tests for vault blob size limits."""

    def test_oversized_blob_rejected(self, client):
        vault_id = make_vault_id()
        sync_token = make_sync_token()
        # Create a blob larger than 5MB
        oversized = base64.b64encode(secrets.token_bytes(5_000_001)).decode()

        response = client.put(
            f"/api/v1/vault/{vault_id}",
            json={"ciphertext": oversized},
            headers={
                "Authorization": f"Bearer {sync_token}",
                "If-None-Match": "*",
            },
        )

        assert response.status_code == 400
        assert "exceeds" in response.json()["detail"]
