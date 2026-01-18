"""Tests for attachment functionality including the one-time retrieval flow."""

import hashlib
import secrets
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from app.main import app
from app.models.secret_attachment import SecretAttachment
from app.routers.secrets import get_storage_service
from app.services.attachment_service import link_attachments_to_secret
from app.services.secret_service import create_secret
from tests.test_api import generate_test_data, solve_pow
from tests.test_utils import utcnow


def compute_payload_hash(ciphertext: bytes, iv: bytes, auth_tag: bytes) -> str:
    """Compute SHA256 hash of payload for PoW binding."""
    return hashlib.sha256(ciphertext + iv + auth_tag).hexdigest()


class TestAttachmentRetrieval:
    """Tests for the one-time secret retrieval with attachments.

    These tests verify that presigned URLs are correctly generated and returned
    when retrieving a secret with attachments, fixing the blocker where attachments
    couldn't be downloaded after retrieve_secret set retrieved_at.
    """

    @pytest.fixture
    def secret_with_attachment(self, db_session):
        """Create a secret with an attachment for testing."""
        test_data = generate_test_data()

        # Create secret that's unlocked (unlock_at in past)
        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=utcnow() - timedelta(hours=1),
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=utcnow() + timedelta(hours=24),
        )

        # Add an attachment directly (simulating what upload_attachment would do)
        attachment = SecretAttachment(
            secret_id=secret.id,
            storage_key="attachments/test-uuid-123",
            encrypted_metadata=b"encrypted_metadata_here",
            metadata_iv=secrets.token_bytes(12),
            metadata_auth_tag=secrets.token_bytes(16),
            blob_iv=secrets.token_bytes(12),
            blob_auth_tag=secrets.token_bytes(16),
            blob_size=1024,
            position=0,
        )
        db_session.add(attachment)
        db_session.commit()

        return secret, attachment, test_data

    def test_retrieve_secret_with_attachment_returns_presigned_url(
        self, client, db_session, secret_with_attachment
    ):
        """Test that retrieving a secret with attachments includes presigned URLs.

        This is a regression test for the blocker: before the fix, attachments
        couldn't be downloaded because retrieved_at was set before the client
        could request presigned URLs.
        """
        secret, attachment, test_data = secret_with_attachment

        # Mock the storage service to return a fake presigned URL
        mock_storage = AsyncMock()
        mock_storage.generate_presigned_url = AsyncMock(
            return_value="https://s3.example.com/bucket/attachments/test-uuid-123?signature=abc123"
        )

        # Override the dependency
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "available"
            assert data["ciphertext"] == test_data["ciphertext"]

            # Verify attachments include presigned URLs
            assert data["attachments"] is not None
            assert len(data["attachments"]) == 1
            att = data["attachments"][0]
            assert att["storage_key"] == "attachments/test-uuid-123"
            assert att["presigned_url"] == (
                "https://s3.example.com/bucket/attachments/test-uuid-123?signature=abc123"
            )
            assert att["blob_size"] == 1024
            assert att["position"] == 0

            # Verify presigned URL was generated with correct parameters
            mock_storage.generate_presigned_url.assert_called_once_with(
                object_key="attachments/test-uuid-123",
                expires_in=300,
            )
        finally:
            # Clean up the override
            app.dependency_overrides.pop(get_storage_service, None)

    def test_second_retrieval_fails_after_first(self, client, db_session, secret_with_attachment):
        """Test that second retrieval returns 404 (one-time semantics preserved)."""
        secret, attachment, test_data = secret_with_attachment

        mock_storage = AsyncMock()
        mock_storage.generate_presigned_url = AsyncMock(
            return_value="https://s3.example.com/presigned"
        )

        # Override the dependency
        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            # First retrieval should succeed
            first_response = client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
            )
            assert first_response.status_code == 200

            # Second retrieval should fail (secret is deleted)
            second_response = client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
            )
            assert second_response.status_code == 404
        finally:
            app.dependency_overrides.pop(get_storage_service, None)

    def test_retrieve_secret_without_attachments_still_works(self, client, db_session):
        """Test that secrets without attachments still retrieve normally."""
        test_data = generate_test_data()

        create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=utcnow() - timedelta(hours=1),
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=utcnow() + timedelta(hours=24),
        )

        response = client.get(
            "/api/v1/secrets/retrieve",
            headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "available"
        assert data["attachments"] is None

    def test_presign_failure_does_not_delete_secret(
        self, client, db_session, secret_with_attachment
    ):
        """Test that presigned URL generation failure does NOT delete the secret.

        This is a regression test for data-loss risk: if presigning fails after
        the secret is deleted, the user permanently loses their secret AND attachments.
        The fix generates presigned URLs BEFORE the destructive retrieve operation.
        """
        secret, attachment, test_data = secret_with_attachment

        # Mock storage to fail presigned URL generation
        mock_storage = AsyncMock()
        mock_storage.generate_presigned_url = AsyncMock(
            side_effect=Exception("S3 connection timeout")
        )

        app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
            )

            # Should return 500 error
            assert response.status_code == 500
            assert "attachment download URLs" in response.json()["detail"]

            # Secret should NOT be deleted - verify it's still retrievable
            db_session.expire_all()
            from app.models.secret import Secret

            refreshed_secret = db_session.query(Secret).filter(Secret.id == secret.id).first()
            assert refreshed_secret is not None
            assert refreshed_secret.retrieved_at is None
            assert refreshed_secret.ciphertext is not None
            assert refreshed_secret.is_deleted is False

            # Verify we can retry (with working storage) and succeed
            mock_storage.generate_presigned_url = AsyncMock(
                return_value="https://s3.example.com/presigned-url"
            )

            retry_response = client.get(
                "/api/v1/secrets/retrieve",
                headers={"Authorization": f"Bearer {test_data['decrypt_token']}"},
            )
            assert retry_response.status_code == 200
            assert retry_response.json()["status"] == "available"
        finally:
            app.dependency_overrides.pop(get_storage_service, None)


class TestAttachmentLinking:
    """Tests for attachment linking during secret creation.

    These tests verify that attachment linking is all-or-nothing:
    if any attachment fails to link, the entire secret creation fails.
    """

    @pytest.fixture
    def orphan_attachment(self, db_session):
        """Create an orphaned attachment (not linked to any secret)."""
        attachment = SecretAttachment(
            secret_id=None,  # Orphaned
            storage_key="attachments/orphan-uuid-456",
            encrypted_metadata=b"encrypted_metadata",
            metadata_iv=secrets.token_bytes(12),
            metadata_auth_tag=secrets.token_bytes(16),
            blob_iv=secrets.token_bytes(12),
            blob_auth_tag=secrets.token_bytes(16),
            blob_size=2048,
            position=0,
        )
        db_session.add(attachment)
        db_session.commit()
        db_session.refresh(attachment)
        return attachment

    def test_secret_creation_fails_if_attachment_not_found(self, client, db_session):
        """Test that creating a secret with non-existent attachment IDs fails."""
        test_data = generate_test_data()

        # Compute payload hash first (needed for challenge creation)
        payload_hash_hex = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get a PoW challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={
                "payload_hash": payload_hash_hex,
                "ciphertext_size": len(test_data["ciphertext_bytes"]),
            },
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Solve PoW
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash_hex)

        # Try to create secret with non-existent attachment ID
        fake_attachment_id = "nonexistent-attachment-id-12345"
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",
                "expiry_preset": "24h",
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash_hex,
                },
                "attachment_ids": [fake_attachment_id],
            },
        )

        assert create_response.status_code == 400
        assert "Failed to link" in create_response.json()["detail"]
        assert "1 of 1 attachments" in create_response.json()["detail"]

    def test_secret_creation_fails_if_some_attachments_not_found(
        self, client, db_session, orphan_attachment
    ):
        """Test that partial attachment linking fails the entire request."""
        test_data = generate_test_data()

        # Compute payload hash first (needed for challenge creation)
        payload_hash_hex = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get a PoW challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={
                "payload_hash": payload_hash_hex,
                "ciphertext_size": len(test_data["ciphertext_bytes"]),
            },
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Solve PoW
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash_hex)

        # Try to create secret with one valid and one invalid attachment ID
        fake_attachment_id = "nonexistent-attachment-id-99999"
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",
                "expiry_preset": "24h",
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash_hex,
                },
                "attachment_ids": [orphan_attachment.id, fake_attachment_id],
            },
        )

        assert create_response.status_code == 400
        assert "Failed to link" in create_response.json()["detail"]
        assert "1 of 2 attachments" in create_response.json()["detail"]

        # Verify the orphan attachment is still orphaned (rollback worked)
        db_session.refresh(orphan_attachment)
        assert orphan_attachment.secret_id is None

    def test_secret_creation_succeeds_with_valid_attachments(
        self, client, db_session, orphan_attachment
    ):
        """Test that secret creation succeeds when all attachments are valid."""
        test_data = generate_test_data()

        # Compute payload hash first (needed for challenge creation)
        payload_hash_hex = compute_payload_hash(
            test_data["ciphertext_bytes"],
            test_data["iv_bytes"],
            test_data["auth_tag_bytes"],
        )

        # Get a PoW challenge
        challenge_response = client.post(
            "/api/v1/challenges",
            json={
                "payload_hash": payload_hash_hex,
                "ciphertext_size": len(test_data["ciphertext_bytes"]),
            },
        )
        assert challenge_response.status_code == 201
        challenge = challenge_response.json()

        # Solve PoW
        counter = solve_pow(challenge["nonce"], challenge["difficulty"], payload_hash_hex)

        # Create secret with valid attachment ID
        create_response = client.post(
            "/api/v1/secrets",
            json={
                "ciphertext": test_data["ciphertext"],
                "iv": test_data["iv"],
                "auth_tag": test_data["auth_tag"],
                "unlock_preset": "now",
                "expiry_preset": "24h",
                "edit_token": test_data["edit_token"],
                "decrypt_token": test_data["decrypt_token"],
                "pow_proof": {
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                    "counter": counter,
                    "payload_hash": payload_hash_hex,
                },
                "attachment_ids": [orphan_attachment.id],
            },
        )

        assert create_response.status_code == 201
        secret_id = create_response.json()["secret_id"]

        # Verify the attachment is now linked to the secret
        db_session.refresh(orphan_attachment)
        assert orphan_attachment.secret_id == secret_id

    def test_link_attachments_returns_count(self, db_session, orphan_attachment):
        """Test that link_attachments_to_secret returns correct count."""
        test_data = generate_test_data()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=utcnow() + timedelta(hours=24),
        )

        # Link existing attachment
        count = link_attachments_to_secret(db_session, secret.id, [orphan_attachment.id])
        assert count == 1

        # Try to link non-existent attachment
        count = link_attachments_to_secret(db_session, secret.id, ["fake-id"])
        assert count == 0

    def test_link_attachments_rejects_already_linked(self, db_session, orphan_attachment):
        """Test that already-linked attachments cannot be re-linked."""
        test_data = generate_test_data()

        # Create first secret and link attachment
        secret1 = create_secret(
            db=db_session,
            ciphertext_b64=test_data["ciphertext"],
            iv_b64=test_data["iv"],
            auth_tag_b64=test_data["auth_tag"],
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=test_data["edit_token"],
            decrypt_token=test_data["decrypt_token"],
            expires_at=utcnow() + timedelta(hours=24),
        )
        count = link_attachments_to_secret(db_session, secret1.id, [orphan_attachment.id])
        assert count == 1

        # Create second secret and try to link same attachment
        test_data2 = generate_test_data()
        secret2 = create_secret(
            db=db_session,
            ciphertext_b64=test_data2["ciphertext"],
            iv_b64=test_data2["iv"],
            auth_tag_b64=test_data2["auth_tag"],
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=test_data2["edit_token"],
            decrypt_token=test_data2["decrypt_token"],
            expires_at=utcnow() + timedelta(hours=24),
        )

        # Should return 0 because attachment is already linked
        count = link_attachments_to_secret(db_session, secret2.id, [orphan_attachment.id])
        assert count == 0
