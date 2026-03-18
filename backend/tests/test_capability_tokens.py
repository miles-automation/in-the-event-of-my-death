"""Comprehensive tests for capability tokens."""

import base64
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.config import settings
from app.services.capability_token_service import (
    consume_capability_token,
    create_capability_token,
    find_capability_token,
    validate_capability_token,
)


def generate_test_data(size: int = 100):
    """Generate test cryptographic data."""
    iv = secrets.token_bytes(12)
    auth_tag = secrets.token_bytes(16)
    ciphertext = secrets.token_bytes(size)
    edit_token = secrets.token_hex(32)
    decrypt_token = secrets.token_hex(32)

    return {
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "iv": base64.b64encode(iv).decode(),
        "auth_tag": base64.b64encode(auth_tag).decode(),
        "edit_token": edit_token,
        "decrypt_token": decrypt_token,
    }


class TestCapabilityTokenCreation:
    """Tests for capability token creation endpoint."""

    def test_create_token_valid_tier(self, client, db_session):
        """Test creating a token with valid tier."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "basic"},
                headers={"X-API-Key": "test-api-key"},
            )

        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert len(data["token"]) == 64  # 32 bytes as hex
        assert data["tier"] == "basic"
        assert data["max_file_size_bytes"] == 10_000_000
        assert data["max_expiry_days"] == 365
        assert "expires_at" in data

    def test_create_token_all_tiers(self, client, db_session):
        """Test creating tokens for all valid tiers."""
        tiers = ["basic", "standard", "large"]
        expected_sizes = [10_000_000, 100_000_000, 500_000_000]

        with patch.object(settings, "internal_api_key", "test-api-key"):
            for tier, expected_size in zip(tiers, expected_sizes):
                response = client.post(
                    "/api/v1/capability-tokens",
                    json={"tier": tier},
                    headers={"X-API-Key": "test-api-key"},
                )
                assert response.status_code == 201
                assert response.json()["max_file_size_bytes"] == expected_size

    def test_create_token_invalid_tier(self, client, db_session):
        """Test creating a token with invalid tier."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "premium"},  # Invalid tier
                headers={"X-API-Key": "test-api-key"},
            )

        assert response.status_code == 422  # Validation error from Pydantic

    def test_create_token_missing_api_key(self, client, db_session):
        """Test creating a token without API key."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "basic"},
            )

        assert response.status_code == 422  # Missing required header

    def test_create_token_wrong_api_key(self, client, db_session):
        """Test creating a token with wrong API key."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "basic"},
                headers={"X-API-Key": "wrong-key"},
            )

        assert response.status_code == 401
        assert "Invalid API key" in response.json()["detail"]

    def test_create_token_not_configured(self, client, db_session):
        """Test creating a token when API key is not configured."""
        with patch.object(settings, "internal_api_key", None):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "basic"},
                headers={"X-API-Key": "any-key"},
            )

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    def test_create_token_with_payment_info(self, client, db_session):
        """Test creating a token with payment information."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={
                    "tier": "standard",
                    "payment_provider": "lightning",
                    "payment_reference": "inv_123456",
                },
                headers={"X-API-Key": "test-api-key"},
            )

        assert response.status_code == 201

        # Verify payment info is stored
        token_data = response.json()
        token = find_capability_token(db_session, token_data["token"])
        assert token.payment_provider == "lightning"
        assert token.payment_reference == "inv_123456"

    def test_create_token_with_metadata(self, client, db_session):
        """Test creating a token with metadata."""
        test_metadata = {
            "recipient_email": "beta@example.com",
            "reason": "beta tester",
            "campaign": "launch-2025",
            "generated_by": "admin",
        }

        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={
                    "tier": "basic",
                    "payment_provider": "github-actions",
                    "payment_reference": "run_12345",
                    "token_metadata": test_metadata,
                },
                headers={"X-API-Key": "test-api-key"},
            )

        assert response.status_code == 201

        # Verify metadata is in response
        data = response.json()
        assert data["token_metadata"] == test_metadata

        # Verify metadata is stored in database
        token = find_capability_token(db_session, data["token"])
        assert token.token_metadata == test_metadata
        assert token.token_metadata["recipient_email"] == "beta@example.com"
        assert token.token_metadata["campaign"] == "launch-2025"

    def test_create_token_without_metadata(self, client, db_session):
        """Test creating a token without metadata (should be None)."""
        with patch.object(settings, "internal_api_key", "test-api-key"):
            response = client.post(
                "/api/v1/capability-tokens",
                json={"tier": "basic"},
                headers={"X-API-Key": "test-api-key"},
            )

        assert response.status_code == 201

        data = response.json()
        assert data["token_metadata"] is None

        token = find_capability_token(db_session, data["token"])
        assert token.token_metadata is None


class TestCapabilityTokenValidation:
    """Tests for capability token validation endpoint."""

    def test_validate_valid_token(self, client, db_session):
        """Test validating a valid token."""
        # Create a token directly
        token_model, raw_token = create_capability_token(db_session, "basic")

        response = client.get(
            "/api/v1/capability-tokens/validate",
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["tier"] == "basic"
        assert data["max_file_size_bytes"] == 10_000_000
        assert data["consumed"] is False

    def test_validate_invalid_token(self, client, db_session):
        """Test validating an invalid token."""
        response = client.get(
            "/api/v1/capability-tokens/validate",
            headers={"X-Capability-Token": secrets.token_hex(32)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["error"] == "Token not found"

    def test_validate_consumed_token(self, client, db_session):
        """Test validating a consumed token."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        consume_capability_token(db_session, token_model, uuid.uuid4())

        response = client.get(
            "/api/v1/capability-tokens/validate",
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["consumed"] is True
        assert "already consumed" in data["error"]

    def test_validate_expired_token(self, client, db_session):
        """Test validating an expired token."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        # Manually expire the token
        token_model.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db_session.commit()

        response = client.get(
            "/api/v1/capability-tokens/validate",
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "expired" in data["error"]

    def test_validate_invalid_format(self, client, db_session):
        """Test validating a token with invalid format."""
        response = client.get(
            "/api/v1/capability-tokens/validate",
            headers={"X-Capability-Token": "too-short"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert "Invalid token format" in data["error"]


class TestSecretCreationWithToken:
    """Tests for secret creation using capability tokens."""

    def test_create_secret_with_token(self, client, db_session):
        """Test creating a secret with a capability token (bypasses PoW)."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        test_data = generate_test_data()

        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
                # No pow_proof!
            },
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 201
        data = response.json()
        assert "secret_id" in data

        # Verify token is consumed
        db_session.refresh(token_model)
        assert token_model.consumed_at is not None
        assert str(token_model.consumed_by_secret_id) == data["secret_id"]

    def test_create_secret_token_consumed_only_once(self, client, db_session):
        """Test that a token can only be used once."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        test_data = generate_test_data()

        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        # First creation should succeed
        response1 = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": raw_token},
        )
        assert response1.status_code == 201

        # Generate new tokens for second attempt
        test_data2 = generate_test_data()

        # Second creation with same token should fail
        response2 = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data2["ciphertext"],
                "iv": test_data2["iv"],
                "auth_tag": test_data2["auth_tag"],
                "edit_token": test_data2["edit_token"],
                "decrypt_token": test_data2["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": raw_token},
        )
        assert response2.status_code == 401
        assert "Invalid or consumed" in response2.json()["detail"]

    def test_create_secret_size_limit_enforced(self, client, db_session):
        """Test that file size limits are enforced per tier."""
        # Create a basic tier token (10MB limit)
        token_model, raw_token = create_capability_token(db_session, "basic")

        # Generate data larger than 10MB (using 15MB)
        test_data = generate_test_data(size=15_000_000)

        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 400
        assert "exceeds token limit" in response.json()["detail"]

        # Verify token is NOT consumed on failure
        db_session.refresh(token_model)
        assert token_model.consumed_at is None

    def test_create_secret_expired_token(self, client, db_session):
        """Test creating a secret with an expired token."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        # Manually expire the token
        token_model.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        db_session.commit()

        test_data = generate_test_data()
        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 401
        assert "expired" in response.json()["detail"]

    def test_create_secret_invalid_token_format(self, client, db_session):
        """Test creating a secret with invalid token format."""
        test_data = generate_test_data()
        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": "invalid-short-token"},
        )

        assert response.status_code == 400
        assert "Invalid capability token format" in response.json()["detail"]

    def test_create_secret_requires_pow_or_token(self, client, db_session):
        """Test that either PoW or capability token is required."""
        test_data = generate_test_data()
        unlock_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
                # No pow_proof and no X-Capability-Token header
            },
        )

        assert response.status_code == 400
        assert "pow_proof or X-Capability-Token" in response.json()["detail"]

    def test_create_secret_token_not_consumed_on_validation_failure(self, client, db_session):
        """Test that token is not consumed when other validations fail."""
        token_model, raw_token = create_capability_token(db_session, "basic")
        test_data = generate_test_data()

        # Invalid dates (expires_at before unlock_at)
        unlock_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "unlock_at": unlock_at,
                "expires_at": expires_at,
            },
            headers={"X-Capability-Token": raw_token},
        )

        assert response.status_code == 422  # Validation error

        # Verify token is NOT consumed
        db_session.refresh(token_model)
        assert token_model.consumed_at is None


class TestCapabilityTokenService:
    """Direct tests for capability token service functions."""

    def test_create_and_find_token(self, db_session):
        """Test creating and finding a token."""
        token_model, raw_token = create_capability_token(db_session, "standard")

        assert token_model.tier == "standard"
        assert token_model.max_file_size_bytes == 100_000_000

        found = find_capability_token(db_session, raw_token)
        assert found is not None
        assert found.id == token_model.id

    def test_find_nonexistent_token(self, db_session):
        """Test finding a token that doesn't exist."""
        found = find_capability_token(db_session, secrets.token_hex(32))
        assert found is None

    def test_validate_token_result(self, db_session):
        """Test validate_capability_token result structure."""
        token_model, raw_token = create_capability_token(db_session, "large")

        result = validate_capability_token(db_session, raw_token)

        assert result["valid"] is True
        assert result["tier"] == "large"
        assert result["max_file_size_bytes"] == 500_000_000
        assert result["max_expiry_days"] == 1825
        assert result["consumed"] is False

    def test_consume_token(self, db_session):
        """Test consuming a token."""
        token_model, raw_token = create_capability_token(db_session, "basic")

        assert token_model.consumed_at is None
        assert token_model.consumed_by_secret_id is None

        fake_secret_id = uuid.uuid4()
        consume_capability_token(db_session, token_model, fake_secret_id)

        assert token_model.consumed_at is not None
        assert token_model.consumed_by_secret_id == fake_secret_id

        # Should not be findable anymore
        found = find_capability_token(db_session, raw_token)
        assert found is None

    def test_create_token_with_metadata_service(self, db_session):
        """Test creating a token with metadata via service function."""
        token_metadata = {
            "recipient_email": "test@example.com",
            "reason": "promo",
            "workflow_run": "12345",
        }

        token_model, raw_token = create_capability_token(
            db_session,
            tier="standard",
            payment_provider="github-actions",
            payment_reference="run_12345",
            token_metadata=token_metadata,
        )

        assert token_model.token_metadata == token_metadata
        assert token_model.token_metadata["recipient_email"] == "test@example.com"
        assert token_model.payment_provider == "github-actions"

        # Verify it persists after finding
        found = find_capability_token(db_session, raw_token)
        assert found.token_metadata == token_metadata
