"""Comprehensive tests for the secrets API."""

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy import select
from starlette.requests import Request

from app.middleware.rate_limit import get_real_client_ip
from app.models.secret import Secret
from tests.test_utils import utcnow


def generate_test_data():
    """Generate test cryptographic data."""
    # Simulating what the frontend would generate
    iv = secrets.token_bytes(12)
    auth_tag = secrets.token_bytes(16)
    ciphertext = secrets.token_bytes(100)  # Fake ciphertext
    edit_token = secrets.token_hex(32)
    decrypt_token = secrets.token_hex(32)

    return {
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "iv": base64.b64encode(iv).decode(),
        "auth_tag": base64.b64encode(auth_tag).decode(),
        "edit_token": edit_token,
        "decrypt_token": decrypt_token,
        "ciphertext_bytes": ciphertext,
        "iv_bytes": iv,
        "auth_tag_bytes": auth_tag,
    }


def compute_payload_hash(ciphertext: bytes, iv: bytes, auth_tag: bytes) -> str:
    """Compute SHA256 hash of payload for PoW binding."""
    return hashlib.sha256(ciphertext + iv + auth_tag).hexdigest()


def solve_pow(nonce: str, difficulty: int, payload_hash: str) -> int:
    """Solve proof-of-work challenge. Returns winning counter."""
    target = 2 ** (256 - difficulty)

    for counter in range(10_000_000):  # Should find solution within this range
        preimage = f"{nonce}{counter:016x}{payload_hash}"
        hash_bytes = hashlib.sha256(preimage.encode()).digest()
        hash_int = int.from_bytes(hash_bytes, "big")

        if hash_int < target:
            return counter

    raise RuntimeError("Failed to solve PoW within iteration limit")


class TestChallenges:
    """Tests for the /challenges endpoint."""

    def test_create_challenge(self, client):
        """Test creating a PoW challenge."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )

        assert response.status_code == 201
        data = response.json()
        assert "challenge_id" in data
        assert "nonce" in data
        assert "difficulty" in data
        assert data["algorithm"] == "sha256"
        assert len(data["nonce"]) == 64  # 32 bytes as hex

    def test_challenge_invalid_payload_hash(self, client):
        """Test creating a challenge with invalid payload hash."""
        response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": "tooshort", "ciphertext_size": 100},
        )

        assert response.status_code == 422  # Validation error


class TestSecrets:
    """Tests for the /secrets endpoints."""

    def test_create_secret_full_flow(self, client):
        """Test creating a secret with full PoW flow."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Step 1: Get challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Step 2: Solve PoW
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Step 3: Create secret
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()

        # Verify secret_id is a valid UUID
        assert "secret_id" in data
        try:
            uuid.UUID(data["secret_id"])
        except ValueError:
            raise AssertionError(f"secret_id is not a valid UUID: {data['secret_id']}")

        # Verify unlock_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "unlock_at" in data
        expected_unlock_at = unlock_at.replace(microsecond=0).isoformat() + "Z"
        assert data["unlock_at"] == expected_unlock_at, (
            f"unlock_at mismatch: expected {expected_unlock_at}, got {data['unlock_at']}"
        )

        # Verify expires_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "expires_at" in data
        expected_expires_at = expires_at.replace(microsecond=0).isoformat() + "Z"
        assert data["expires_at"] == expected_expires_at, (
            f"expires_at mismatch: expected {expected_expires_at}, got {data['expires_at']}"
        )

        # Verify created_at is a valid recent timestamp
        assert "created_at" in data
        # Parse the created_at timestamp and verify it's within last minute
        created_at_dt = datetime.fromisoformat(data["created_at"].rstrip("Z"))
        time_diff = abs((utcnow() - created_at_dt).total_seconds())
        assert time_diff < 60, (
            f"created_at is not recent: {data['created_at']} (diff: {time_diff}s)"
        )

    def test_retrieve_before_unlock(self, client):
        """Test that retrieval before unlock date is rejected."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with future unlock date
        unlock_at = utcnow() + timedelta(days=1)
        expires_at = utcnow() + timedelta(days=7)
        client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        # Try to retrieve before unlock
        retrieve_response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert retrieve_response.status_code == 403

    def test_status_check(self, client):
        """Test the non-destructive status check endpoint."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        # Check status
        status_response = client.get(
            "/api/v1/secrets/status",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["exists"] is True
        assert data["status"] == "pending"

        # Verify unlock_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "unlock_at" in data
        expected_unlock_at = unlock_at.replace(microsecond=0).isoformat() + "Z"
        assert data["unlock_at"] == expected_unlock_at, (
            f"unlock_at mismatch: expected {expected_unlock_at}, got {data['unlock_at']}"
        )

        # Verify expires_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "expires_at" in data
        expected_expires_at = expires_at.replace(microsecond=0).isoformat() + "Z"
        assert data["expires_at"] == expected_expires_at, (
            f"expires_at mismatch: expected {expected_expires_at}, got {data['expires_at']}"
        )

    def test_status_check_by_id(self, client, db_session):
        """Test the public status endpoint by secret ID."""
        from app.services.secret_service import create_secret

        test_data = generate_test_data()
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)

        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=unlock_at,
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=expires_at,
        )

        status_response = client.get(f"/api/v1/secrets/{secret.id}/status")

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["id"] == str(secret.id)
        assert data["exists"] is True
        assert data["status"] == "pending"
        assert "unlock_at" in data
        assert "expires_at" in data

    def test_status_check_by_id_unlocked(self, client, db_session):
        """Test the public status endpoint returns unlocked when past unlock_at."""
        from app.services.secret_service import create_secret

        test_data = generate_test_data()
        unlock_at = utcnow() - timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)

        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=unlock_at,
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=expires_at,
        )

        status_response = client.get(f"/api/v1/secrets/{secret.id}/status")

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["id"] == str(secret.id)
        assert data["exists"] is True
        assert data["status"] == "unlocked"

    def test_status_check_by_id_expired(self, client, db_session):
        """Test the public status endpoint returns expired when past expires_at."""
        from app.services.secret_service import create_secret

        test_data = generate_test_data()
        unlock_at = utcnow() - timedelta(days=8)
        expires_at = utcnow() - timedelta(hours=1)

        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=unlock_at,
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=expires_at,
        )

        status_response = client.get(f"/api/v1/secrets/{secret.id}/status")

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["id"] == str(secret.id)
        assert data["exists"] is True
        assert data["status"] == "expired"

    def test_status_check_by_id_retrieved(self, client, db_session):
        """Test the public status endpoint returns retrieved after one-time retrieval."""
        from app.services.secret_service import create_secret, retrieve_secret

        test_data = generate_test_data()
        unlock_at = utcnow() - timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)

        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=unlock_at,
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=expires_at,
        )
        retrieve_secret(db_session, secret)

        status_response = client.get(f"/api/v1/secrets/{secret.id}/status")

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["id"] == str(secret.id)
        assert data["exists"] is True
        assert data["status"] == "retrieved"

    def test_status_check_by_id_not_found(self, client):
        """Test the public status endpoint returns 404 for unknown secrets."""
        missing_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/secrets/{missing_id}/status")
        assert response.status_code == 404

    def test_invalid_token(self, client):
        """Test that invalid tokens are rejected."""
        response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": "Bearer " + "a" * 64},
        )

        assert response.status_code == 404

    def test_edit_page_can_get_status_with_edit_token(self, client):
        """
        The edit page needs to check secret status using the edit token.
        Currently this fails because /secrets/status only accepts decrypt tokens.
        """
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret
        unlock_at = utcnow() + timedelta(hours=24)
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )
        assert create_response.status_code == 201

        # The edit page uses the edit token to get status
        # This should work but currently fails
        status_response = client.get(
            "/api/v1/secrets/edit/status",
            headers={"Authorization": f"Bearer {test_data['edit_token']}"},
        )

        assert status_response.status_code == 200
        data = status_response.json()
        assert data["exists"] is True
        assert data["status"] == "pending"
        assert "unlock_at" in data
        assert "expires_at" in data

    def test_pow_challenge_reuse_rejected(self, client):
        """Test that PoW challenges cannot be reused."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create first secret
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        first_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )
        assert first_response.status_code == 201

        # Try to reuse the same challenge
        test_data2 = generate_test_data()
        second_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data2["ciphertext"],
                "iv": test_data2["iv"],
                "auth_tag": test_data2["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data2["edit_token"],
                "decrypt_token": test_data2["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,  # Using same payload hash
                },
            },
        )

        assert second_response.status_code == 400
        assert "already used" in second_response.json()["detail"]


class TestValidation:
    """Tests for input validation."""

    def test_invalid_iv_size(self, client):
        """Test that IV must be exactly 12 bytes."""
        test_data = generate_test_data()
        test_data["iv"] = base64.b64encode(secrets.token_bytes(16)).decode()  # Wrong size

        payload_hash = "a" * 64  # Fake hash
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()

        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": 0,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert response.status_code == 422
        assert "12 bytes" in str(response.json())

    def test_invalid_auth_tag_size(self, client):
        """Test that auth tag must be exactly 16 bytes."""
        test_data = generate_test_data()
        test_data["auth_tag"] = base64.b64encode(secrets.token_bytes(12)).decode()  # Wrong size

        payload_hash = "a" * 64
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()

        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": 0,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert response.status_code == 422
        assert "16 bytes" in str(response.json())

    def test_unlock_date_in_past(self, client):
        """Test that unlock date cannot be in the past."""
        test_data = generate_test_data()
        payload_hash = "a" * 64

        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()

        unlock_at = utcnow() - timedelta(hours=1)  # In the past
        expires_at = utcnow() + timedelta(days=7)
        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": 0,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert response.status_code == 422
        error_msg = str(response.json()).lower()
        assert "past" in error_msg or "future" in error_msg


class TestPowHardening:
    """Tests for PoW binding and difficulty enforcement."""

    def test_payload_hash_must_match_ciphertext(self, client):
        """PoW solved for one payload cannot be used for different payload."""
        # Generate original test data and get challenge
        original_data = generate_test_data()
        original_hash = compute_payload_hash(
            original_data["ciphertext_bytes"],
            original_data["iv_bytes"],
            original_data["auth_tag_bytes"],
        )

        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": original_hash, "ciphertext_size": 100},
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Solve PoW for original payload
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], original_hash)

        # Try to create secret with DIFFERENT ciphertext but same PoW proof
        different_data = generate_test_data()
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)

        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": different_data["ciphertext"],  # Different!
                "iv": different_data["iv"],
                "auth_tag": different_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": different_data["edit_token"],
                "decrypt_token": different_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": original_hash,  # Original hash in proof
                },
            },
        )

        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"].lower()

    def test_overpay_difficulty_allowed(self, client):
        """Can use high-difficulty challenge for smaller payload (overpay is OK)."""
        # Generate small payload
        small_data = generate_test_data()
        payload_hash = compute_payload_hash(
            small_data["ciphertext_bytes"],
            small_data["iv_bytes"],
            small_data["auth_tag_bytes"],
        )

        # Request challenge claiming slightly larger size to get +1 difficulty
        # 100KB = base + 1 bit difficulty
        challenge_response = client.post(
            "/api/v1/challenges",
            json={
                "payload_hash": payload_hash,
                "ciphertext_size": 100_000,  # Claim 100KB, actual is ~100 bytes
            },
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Difficulty should be base + 1 for 100KB
        assert challenge["difficulty"] == 18 + 1  # Base + 1 for 100KB

        # Solve the slightly harder challenge (still fast enough for tests)
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Submit with actual small data - should succeed (overpay OK)
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": small_data["ciphertext"],
                "iv": small_data["iv"],
                "auth_tag": small_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": small_data["edit_token"],
                "decrypt_token": small_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert response.status_code == 201

    def test_challenge_not_burned_on_validation_failure(self, client):
        """Challenge should not be marked used if secret creation fails validation."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret with invalid unlock date (in the past)
        unlock_at = utcnow() - timedelta(hours=1)  # Invalid - in the past
        expires_at = utcnow() + timedelta(days=7)
        first_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )
        assert first_response.status_code == 422  # Validation error

        # Now try again with valid unlock date - should work because challenge wasn't burned
        valid_unlock_at = utcnow() + timedelta(hours=1)
        second_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": valid_unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )
        assert second_response.status_code == 201


class TestExpiryFeature:
    """Tests for the expiry feature."""

    def test_create_secret_with_expires_at(self, client):
        """Test creating a secret with expires_at field."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with expires_at
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=2)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()

        # Verify secret_id is a valid UUID
        assert "secret_id" in data
        try:
            uuid.UUID(data["secret_id"])
        except ValueError:
            raise AssertionError(f"secret_id is not a valid UUID: {data['secret_id']}")

        # Verify unlock_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "unlock_at" in data
        expected_unlock_at = unlock_at.replace(microsecond=0).isoformat() + "Z"
        assert data["unlock_at"] == expected_unlock_at, (
            f"unlock_at mismatch: expected {expected_unlock_at}, got {data['unlock_at']}"
        )

        # Verify expires_at matches input (API adds 'Z' suffix and truncates to seconds)
        assert "expires_at" in data
        expected_expires_at = expires_at.replace(microsecond=0).isoformat() + "Z"
        assert data["expires_at"] == expected_expires_at, (
            f"expires_at mismatch: expected {expected_expires_at}, got {data['expires_at']}"
        )

        # Verify created_at is a valid recent timestamp
        assert "created_at" in data
        # Parse the created_at timestamp and verify it's within last minute
        created_at_dt = datetime.fromisoformat(data["created_at"].rstrip("Z"))
        time_diff = abs((utcnow() - created_at_dt).total_seconds())
        assert time_diff < 60, (
            f"created_at is not recent: {data['created_at']} (diff: {time_diff}s)"
        )

    def test_create_secret_without_expires_at_rejected(self, client):
        """Test that creating a secret without expires_at is rejected (required field)."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret without expires_at
        unlock_at = utcnow() + timedelta(hours=1)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                # expires_at intentionally omitted
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422  # Validation error - missing required field

    def test_expires_at_minimum_gap_enforced(self, client):
        """Test that expires_at must be at least 15 minutes after unlock_at."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret with expires_at only 5 minutes after unlock_at
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = unlock_at + timedelta(minutes=5)  # Only 5 minutes gap - too short
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422
        assert "15 minutes" in str(create_response.json()).lower()

    def test_expires_at_must_be_after_unlock_at(self, client):
        """Test that expires_at must be after unlock_at."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret with expires_at before unlock_at
        unlock_at = utcnow() + timedelta(hours=2)
        expires_at = utcnow() + timedelta(hours=1)  # Before unlock_at
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422
        assert "after unlock_at" in str(create_response.json()).lower()

    def test_expires_at_equal_to_unlock_at_rejected(self, client):
        """Test that expires_at equal to unlock_at is rejected."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret with expires_at equal to unlock_at
        unlock_at = utcnow() + timedelta(hours=2)
        expires_at = unlock_at  # Same as unlock_at
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422
        assert "after unlock_at" in str(create_response.json()).lower()

    def test_status_includes_expires_at(self, client):
        """Test that status endpoint includes expires_at."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with expires_at
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=2)
        client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        # Check status
        status_response = client.get(
            "/api/v1/secrets/status",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert status_response.status_code == 200
        data = status_response.json()
        assert "expires_at" in data
        assert data["expires_at"] is not None


class TestRetrieveEndpoint:
    """Tests for the /secrets/retrieve endpoint success and error paths."""

    def _create_secret_via_api(self, client, db_session, test_data=None):
        """Helper to create a secret through the API and return the db record.

        Returns tuple of (secret, test_data) where secret is the SQLAlchemy model instance.
        """
        if test_data is None:
            test_data = generate_test_data()

        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with future unlock date
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_at": unlock_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )
        assert create_response.status_code == 201

        # Get the secret from the database
        stmt = select(Secret).where(Secret.decrypt_token_prefix == test_data["decrypt_token"][:16])
        secret = db_session.scalars(stmt).first()
        assert secret is not None

        return secret, test_data

    def test_retrieve_after_unlock_success(self, client, db_session):
        """Test successful retrieval after unlock returns correct data."""
        secret, test_data = self._create_secret_via_api(client, db_session)

        # Set unlock_at to the past to simulate time passing
        secret.unlock_at = utcnow() - timedelta(hours=1)
        db_session.commit()

        # Retrieve the secret
        retrieve_response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert retrieve_response.status_code == 200
        data = retrieve_response.json()
        assert data["status"] == "available"
        assert data["ciphertext"] == test_data["ciphertext"]
        assert data["iv"] == test_data["iv"]
        assert data["auth_tag"] == test_data["auth_tag"]

    def test_retrieve_already_retrieved_returns_404(self, client, db_session):
        """Test that retrieving twice returns 404 (secret is logically deleted after retrieval).

        After successful retrieval, the secret is marked as deleted and excluded from lookups.
        This is intentional for security - it prevents probing to see if a secret ever existed.
        """
        secret, test_data = self._create_secret_via_api(client, db_session)

        # Set unlock_at to the past
        secret.unlock_at = utcnow() - timedelta(hours=1)
        db_session.commit()

        # First retrieval should succeed
        first_response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )
        assert first_response.status_code == 200

        # Second retrieval returns 404 because secret is now logically deleted
        # (This is correct security behavior - doesn't reveal if secret ever existed)
        second_response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )
        assert second_response.status_code == 404
        assert second_response.json()["detail"] == "Secret not found"

    def test_retrieve_expired_returns_410(self, client, db_session):
        """Test that expired secrets return 410 with 'expired' status."""
        secret, test_data = self._create_secret_via_api(client, db_session)

        # Set unlock_at and expires_at to past (secret is now expired)
        secret.unlock_at = utcnow() - timedelta(days=2)
        secret.expires_at = utcnow() - timedelta(hours=1)
        db_session.commit()

        # Attempt to retrieve expired secret
        retrieve_response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert retrieve_response.status_code == 410
        detail = retrieve_response.json()["detail"]
        assert detail["status"] == "expired"
        assert "expires_at" in detail
        assert "message" in detail


class TestUnlockPreset:
    """Tests for server-side unlock_preset feature."""

    def test_create_secret_with_unlock_preset_now(self, client):
        """Test creating a secret with unlock_preset='now' (server-calculated)."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with unlock_preset instead of unlock_at
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",  # Server calculates unlock_at
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert "unlock_at" in data
        # unlock_at should be close to now (within 1 minute)
        unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
        time_diff = abs((utcnow() - unlock_at).total_seconds())
        assert time_diff < 60, f"unlock_at is not recent: {data['unlock_at']}"

    def test_create_secret_with_unlock_preset_1h(self, client):
        """Test creating a secret with unlock_preset='1h' (1 hour from now)."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with unlock_preset='1h'
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "1h",  # 1 hour from now
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert "unlock_at" in data
        # unlock_at should be about 1 hour from now (within 1 minute tolerance)
        unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
        expected = utcnow() + timedelta(hours=1)
        time_diff = abs((expected - unlock_at).total_seconds())
        assert time_diff < 60, f"unlock_at should be ~1 hour from now, got {data['unlock_at']}"

    def test_create_secret_with_unlock_preset_1w(self, client):
        """Test creating a secret with unlock_preset='1w' (1 week from now)."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with unlock_preset='1w'
        expires_at = utcnow() + timedelta(weeks=2)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "1w",  # 1 week from now
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()
        assert "unlock_at" in data
        # unlock_at should be about 1 week from now (within 1 minute tolerance)
        unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
        expected = utcnow() + timedelta(weeks=1)
        time_diff = abs((expected - unlock_at).total_seconds())
        assert time_diff < 60, f"unlock_at should be ~1 week from now, got {data['unlock_at']}"

    def test_create_secret_without_unlock_at_or_preset_rejected(self, client):
        """Test that creating a secret without unlock_at or unlock_preset is rejected."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret without unlock_at or unlock_preset
        expires_at = utcnow() + timedelta(days=7)
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                # No unlock_at or unlock_preset
                "expires_at": expires_at.isoformat(),
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422
        assert (
            "unlock_at" in str(create_response.json()).lower()
            or "unlock_preset" in str(create_response.json()).lower()
        )

    def test_unlock_preset_all_values(self, client):
        """Test all valid unlock_preset values."""
        presets = ["now", "15m", "1h", "24h", "1w"]
        expected_offsets = {
            "now": timedelta(seconds=0),
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "1w": timedelta(weeks=1),
        }

        for preset in presets:
            test_data = generate_test_data()
            payload_hash = compute_payload_hash(
                test_data["ciphertext_bytes"],
                test_data["iv_bytes"],
                test_data["auth_tag_bytes"],
            )

            # Get challenge and solve PoW
            challenge_response = client.post(
                "/api/v1/challenges",
                json={"payload_hash": payload_hash, "ciphertext_size": 100},
            )
            challenge = challenge_response.json()
            counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

            # Create secret with this preset
            expires_at = utcnow() + timedelta(weeks=2)
            create_response = client.post(
                "/api/v1/secrets",
                json={
                    "ciphertext": test_data["ciphertext"],
                    "iv": test_data["iv"],
                    "auth_tag": test_data["auth_tag"],
                    "unlock_preset": preset,
                    "expires_at": expires_at.isoformat(),
                    "edit_token": test_data["edit_token"],
                    "decrypt_token": test_data["decrypt_token"],
                    "pow_proof": {
                        "challenge_id": challenge["challenge_id"],
                        "nonce": challenge["nonce"],
                        "counter": counter,
                        "payload_hash": payload_hash,
                    },
                },
            )

            assert create_response.status_code == 201, f"Failed for preset={preset}"
            data = create_response.json()

            # Verify unlock_at is approximately correct
            unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
            expected = utcnow() + expected_offsets[preset]
            time_diff = abs((expected - unlock_at).total_seconds())
            assert time_diff < 60, f"unlock_at wrong for preset={preset}: {data['unlock_at']}"


class TestExpiryPreset:
    """Tests for server-side expiry_preset feature."""

    def test_create_secret_with_expiry_preset(self, client):
        """Test creating a secret with expiry_preset (server-calculated)."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Create secret with both unlock_preset and expiry_preset
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",
                "expiry_preset": "1h",  # 1 hour after unlock
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 201
        data = create_response.json()

        # Verify times
        unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
        expires_at = datetime.fromisoformat(data["expires_at"].rstrip("Z"))

        # unlock_at should be now
        time_diff = abs((utcnow() - unlock_at).total_seconds())
        assert time_diff < 60, f"unlock_at is not recent: {data['unlock_at']}"

        # expires_at should be 1 hour after unlock_at
        gap = (expires_at - unlock_at).total_seconds()
        expected_gap = 3600  # 1 hour
        assert abs(gap - expected_gap) < 60, f"expiry gap wrong: {gap}s, expected ~{expected_gap}s"

    def test_expiry_preset_all_values(self, client):
        """Test all valid expiry_preset values."""
        presets = ["15m", "1h", "24h", "1w"]
        expected_gaps = {
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "1w": timedelta(weeks=1),
        }

        for preset in presets:
            test_data = generate_test_data()
            payload_hash = compute_payload_hash(
                test_data["ciphertext_bytes"],
                test_data["iv_bytes"],
                test_data["auth_tag_bytes"],
            )

            # Get challenge and solve PoW
            challenge_response = client.post(
                "/api/v1/challenges",
                json={"payload_hash": payload_hash, "ciphertext_size": 100},
            )
            challenge = challenge_response.json()
            counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

            # Create secret with expiry preset
            create_response = client.post(
                "/api/v1/secrets",
                json={
                    "ciphertext": test_data["ciphertext"],
                    "iv": test_data["iv"],
                    "auth_tag": test_data["auth_tag"],
                    "unlock_preset": "now",
                    "expiry_preset": preset,
                    "edit_token": test_data["edit_token"],
                    "decrypt_token": test_data["decrypt_token"],
                    "pow_proof": {
                        "challenge_id": challenge["challenge_id"],
                        "nonce": challenge["nonce"],
                        "counter": counter,
                        "payload_hash": payload_hash,
                    },
                },
            )

            assert create_response.status_code == 201, f"Failed for preset={preset}"
            data = create_response.json()

            # Verify gap between unlock and expiry
            unlock_at = datetime.fromisoformat(data["unlock_at"].rstrip("Z"))
            expires_at = datetime.fromisoformat(data["expires_at"].rstrip("Z"))
            actual_gap = expires_at - unlock_at
            expected = expected_gaps[preset]
            diff = abs((actual_gap - expected).total_seconds())
            assert diff < 60, f"gap wrong for preset={preset}: {actual_gap}, expected {expected}"

    def test_create_secret_without_expires_at_or_preset_rejected(self, client):
        """Test that creating a secret without expires_at or expiry_preset is rejected."""
        test_data = generate_test_data()
        payload_hash = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get challenge and solve PoW
        challenge_response = client.post(
            "/api/v1/challenges",
            json={"payload_hash": payload_hash, "ciphertext_size": 100},
        )
        challenge = challenge_response.json()
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash)

        # Try to create secret without expires_at or expiry_preset
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",
                # No expires_at or expiry_preset
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash,
                },
            },
        )

        assert create_response.status_code == 422
        assert (
            "expires_at" in str(create_response.json()).lower()
            or "expiry_preset" in str(create_response.json()).lower()
        )


class TestRateLimitClientIP:
    """Tests for rate limiting client IP extraction."""

    def test_x_forwarded_for_single_ip(self):
        """Test that X-Forwarded-For header is respected."""
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "203.0.113.195"}
        request.client.host = "10.0.0.1"

        result = get_real_client_ip(request)

        assert result == "203.0.113.195"

    def test_x_forwarded_for_multiple_ips(self):
        """Test that first IP is extracted from X-Forwarded-For chain."""
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
        request.client.host = "10.0.0.1"

        result = get_real_client_ip(request)

        assert result == "203.0.113.195"

    def test_x_forwarded_for_with_whitespace(self):
        """Test that whitespace is stripped from IP addresses."""
        request = MagicMock(spec=Request)
        request.headers = {"X-Forwarded-For": "  203.0.113.195  , 70.41.3.18"}
        request.client.host = "10.0.0.1"

        result = get_real_client_ip(request)

        assert result == "203.0.113.195"

    def test_fallback_to_client_host(self):
        """Test fallback to request.client.host when no X-Forwarded-For."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client.host = "192.168.1.100"

        result = get_real_client_ip(request)

        assert result == "192.168.1.100"

    def test_fallback_when_no_client(self):
        """Test fallback to 'unknown' when request.client is None."""
        request = MagicMock(spec=Request)
        request.headers = {}
        request.client = None

        result = get_real_client_ip(request)

        assert result == "unknown"
