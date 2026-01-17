"""Tests for the secret service functions."""

import base64
import secrets
from datetime import timedelta

import pytest

from app.services.secret_service import (
    TOKEN_PREFIX_LENGTH,
    clear_expired_secrets,
    clear_secret_and_attachments,
    create_secret,
    find_secret_by_decrypt_token,
    find_secret_by_edit_token,
    get_secrets_needing_cleanup,
    get_token_prefix,
    retrieve_secret,
)
from tests.test_utils import utcnow


@pytest.fixture
def sample_tokens():
    """Generate sample tokens for testing."""
    return {
        "edit_token": secrets.token_hex(32),
        "decrypt_token": secrets.token_hex(32),
    }


class TestClearExpiredSecrets:
    """Tests for the clear_expired_secrets function."""

    def test_clear_expired_secrets(self, db_session, sample_tokens):
        """Test that expired secrets have their ciphertext cleared."""
        # Create test data
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an expired secret (expires in the past)
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() - timedelta(hours=1)  # Already expired
        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=unlock_at,
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=expires_at,
        )

        # Verify it's not cleared yet
        assert expired_secret.cleared_at is None
        assert expired_secret.ciphertext is not None

        # Run the clear expired secrets function
        cleared_count, storage_keys = clear_expired_secrets(db_session)

        # Verify the secret was cleared
        assert cleared_count == 1
        assert storage_keys == []  # No attachments
        db_session.refresh(expired_secret)
        assert expired_secret.cleared_at is not None
        assert expired_secret.ciphertext is None
        assert expired_secret.iv is None
        assert expired_secret.auth_tag is None
        # Metadata should be preserved (row not deleted)
        assert expired_secret.id is not None
        assert expired_secret.unlock_at is not None
        assert expired_secret.expires_at is not None
        assert expired_secret.created_at is not None

    def test_clear_retrieved_secrets(self, db_session, sample_tokens):
        """Test that retrieved secrets have their ciphertext cleared."""
        # Create test data
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create a secret that has been retrieved (not yet expired)
        unlock_at = utcnow() - timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=30)  # Not expired
        retrieved_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=unlock_at,
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=expires_at,
        )

        # Mark as retrieved (simulating what retrieve_secret does)
        retrieved_secret.retrieved_at = utcnow() - timedelta(minutes=30)
        retrieved_secret.is_deleted = True
        db_session.commit()

        # Verify it's not cleared yet
        assert retrieved_secret.cleared_at is None
        assert retrieved_secret.ciphertext is not None

        # Run the clear function
        cleared_count, storage_keys = clear_expired_secrets(db_session)

        # Verify the secret was cleared
        assert cleared_count == 1
        assert storage_keys == []  # No attachments
        db_session.refresh(retrieved_secret)
        assert retrieved_secret.cleared_at is not None
        assert retrieved_secret.ciphertext is None
        assert retrieved_secret.iv is None
        assert retrieved_secret.auth_tag is None
        # Metadata should be preserved (row not deleted)
        assert retrieved_secret.id is not None
        assert retrieved_secret.retrieved_at is not None

    def test_dont_clear_non_expired_non_retrieved_secrets(self, db_session, sample_tokens):
        """Test that active secrets (not expired, not retrieved) are not cleared."""
        # Create test data
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create a non-expired, non-retrieved secret
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() + timedelta(days=2)  # Not expired
        active_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=unlock_at,
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=expires_at,
        )

        # Run the clear function
        cleared_count, storage_keys = clear_expired_secrets(db_session)

        # Verify the secret was not cleared
        assert cleared_count == 0
        assert storage_keys == []
        db_session.refresh(active_secret)
        assert active_secret.cleared_at is None
        assert active_secret.ciphertext is not None

    def test_dont_clear_already_cleared_secrets(self, db_session, sample_tokens):
        """Test that already cleared secrets are not processed again."""
        # Create test data
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an expired secret
        unlock_at = utcnow() + timedelta(hours=1)
        expires_at = utcnow() - timedelta(hours=1)  # Already expired
        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=unlock_at,
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=expires_at,
        )

        # Clear it once
        cleared_count, storage_keys = clear_expired_secrets(db_session)
        assert cleared_count == 1
        assert storage_keys == []
        db_session.refresh(expired_secret)
        first_cleared_at = expired_secret.cleared_at

        # Try to clear again
        cleared_count, storage_keys = clear_expired_secrets(db_session)

        # Verify nothing was cleared (already processed)
        assert cleared_count == 0
        assert storage_keys == []
        db_session.refresh(expired_secret)
        assert expired_secret.cleared_at == first_cleared_at


class TestTokenPrefixLookup:
    """Tests for token prefix-based O(1) lookup."""

    def test_get_token_prefix(self):
        """Test that get_token_prefix extracts first 16 chars."""
        token = "abcdef1234567890xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        prefix = get_token_prefix(token)
        assert prefix == "abcdef1234567890"
        assert len(prefix) == TOKEN_PREFIX_LENGTH

    def test_create_secret_stores_prefixes(self, db_session, sample_tokens):
        """Test that create_secret stores token prefixes."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # Verify prefixes are stored correctly
        assert secret.edit_token_prefix == sample_tokens["edit_token"][:TOKEN_PREFIX_LENGTH]
        assert secret.decrypt_token_prefix == sample_tokens["decrypt_token"][:TOKEN_PREFIX_LENGTH]

    def test_find_secret_by_edit_token_uses_prefix(self, db_session, sample_tokens):
        """Test that find_secret_by_edit_token uses prefix for lookup."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        created = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # Find by edit token
        found = find_secret_by_edit_token(db_session, sample_tokens["edit_token"])
        assert found is not None
        assert found.id == created.id

        # Wrong token should not find it
        wrong_token = secrets.token_hex(32)
        not_found = find_secret_by_edit_token(db_session, wrong_token)
        assert not_found is None

    def test_find_secret_by_decrypt_token_uses_prefix(self, db_session, sample_tokens):
        """Test that find_secret_by_decrypt_token uses prefix for lookup."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        created = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # Find by decrypt token
        found = find_secret_by_decrypt_token(db_session, sample_tokens["decrypt_token"])
        assert found is not None
        assert found.id == created.id

        # Wrong token should not find it
        wrong_token = secrets.token_hex(32)
        not_found = find_secret_by_decrypt_token(db_session, wrong_token)
        assert not_found is None

    def test_deleted_secrets_not_found_by_token(self, db_session, sample_tokens):
        """Test that deleted secrets are not returned by token lookup."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # Mark as deleted
        secret.is_deleted = True
        db_session.commit()

        # Should not be found
        found_by_edit = find_secret_by_edit_token(db_session, sample_tokens["edit_token"])
        found_by_decrypt = find_secret_by_decrypt_token(db_session, sample_tokens["decrypt_token"])
        assert found_by_edit is None
        assert found_by_decrypt is None


class TestRetrieveSecret:
    """Tests for the retrieve_secret function."""

    def test_retrieve_secret_clears_ciphertext_immediately(self, db_session, sample_tokens):
        """Test that ciphertext is cleared in the same transaction as retrieval."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an unlocked secret (unlock_at in the past)
        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() - timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # Verify ciphertext exists before retrieval
        assert secret.ciphertext is not None
        assert secret.iv is not None
        assert secret.auth_tag is not None
        assert secret.cleared_at is None

        # Retrieve the secret
        result = retrieve_secret(db_session, secret)

        # Verify retrieval was successful and returned data
        assert result["status"] == "available"
        assert result["ciphertext"] == ciphertext
        assert result["iv"] == iv
        assert result["auth_tag"] == auth_tag

        # Verify ciphertext is cleared immediately (in same transaction)
        db_session.refresh(secret)
        assert secret.ciphertext is None
        assert secret.iv is None
        assert secret.auth_tag is None
        assert secret.cleared_at is not None
        assert secret.retrieved_at is not None
        assert secret.is_deleted is True

    def test_retrieve_secret_already_retrieved(self, db_session, sample_tokens):
        """Test that already retrieved secrets return appropriate status."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() - timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        # First retrieval
        result1 = retrieve_secret(db_session, secret)
        assert result1["status"] == "available"

        # Second retrieval attempt
        result2 = retrieve_secret(db_session, secret)
        assert result2["status"] == "retrieved"

    def test_retrieve_secret_not_yet_unlocked(self, db_session, sample_tokens):
        """Test that secrets not yet unlocked return pending status."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),  # Future unlock
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() + timedelta(days=7),
        )

        result = retrieve_secret(db_session, secret)
        assert result["status"] == "pending"
        # Ciphertext should NOT be cleared
        db_session.refresh(secret)
        assert secret.ciphertext is not None
        assert secret.cleared_at is None

    def test_retrieve_secret_expired(self, db_session, sample_tokens):
        """Test that expired secrets return expired status."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() - timedelta(days=2),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() - timedelta(hours=1),  # Already expired
        )

        result = retrieve_secret(db_session, secret)
        assert result["status"] == "expired"


class TestAttachmentCleanup:
    """Tests for attachment-aware cleanup functions."""

    def test_get_secrets_needing_cleanup_expired(self, db_session, sample_tokens):
        """Test that expired secrets are returned for cleanup."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an expired secret
        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() - timedelta(hours=1),
        )

        result = get_secrets_needing_cleanup(db_session)

        assert len(result) == 1
        secret_id, storage_keys = result[0]
        assert secret_id == expired_secret.id
        assert storage_keys == []  # No attachments

    def test_get_secrets_needing_cleanup_with_attachment(self, db_session, sample_tokens):
        """Test that secrets with attachments return their storage keys."""
        from app.models.secret_attachment import SecretAttachment

        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an expired secret
        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() - timedelta(hours=1),
        )

        # Add an attachment
        attachment = SecretAttachment(
            secret_id=expired_secret.id,
            storage_key="test-bucket/secrets/test-key-123",
            encrypted_metadata=b"encrypted_metadata",
            metadata_iv=secrets.token_bytes(12),
            metadata_auth_tag=secrets.token_bytes(16),
            blob_iv=secrets.token_bytes(12),
            blob_auth_tag=secrets.token_bytes(16),
            blob_size=1024,
            position=0,
        )
        db_session.add(attachment)
        db_session.commit()

        result = get_secrets_needing_cleanup(db_session)

        assert len(result) == 1
        secret_id, storage_keys = result[0]
        assert secret_id == expired_secret.id
        assert storage_keys == ["test-bucket/secrets/test-key-123"]

    def test_clear_secret_and_attachments_deletes_attachment_rows(self, db_session, sample_tokens):
        """Test that clearing a secret also deletes its attachment rows."""
        from app.models.secret_attachment import SecretAttachment

        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        # Create an expired secret
        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() - timedelta(hours=1),
        )

        # Add an attachment
        attachment = SecretAttachment(
            secret_id=expired_secret.id,
            storage_key="test-bucket/secrets/test-key-456",
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

        # Verify attachment exists
        assert (
            db_session.query(SecretAttachment)
            .filter(SecretAttachment.secret_id == expired_secret.id)
            .count()
            == 1
        )

        # Clear the secret
        result = clear_secret_and_attachments(db_session, expired_secret.id)

        assert result is True

        # Verify secret is cleared
        db_session.refresh(expired_secret)
        assert expired_secret.cleared_at is not None
        assert expired_secret.ciphertext is None

        # Verify attachment row is deleted
        assert (
            db_session.query(SecretAttachment)
            .filter(SecretAttachment.secret_id == expired_secret.id)
            .count()
            == 0
        )

    def test_clear_secret_and_attachments_already_cleared(self, db_session, sample_tokens):
        """Test that already-cleared secrets return False."""
        iv = base64.b64encode(secrets.token_bytes(12)).decode()
        auth_tag = base64.b64encode(secrets.token_bytes(16)).decode()
        ciphertext = base64.b64encode(secrets.token_bytes(100)).decode()

        expired_secret = create_secret(
            db=db_session,
            ciphertext_b64=ciphertext,
            iv_b64=iv,
            auth_tag_b64=auth_tag,
            unlock_at=utcnow() + timedelta(hours=1),
            edit_token=sample_tokens["edit_token"],
            decrypt_token=sample_tokens["decrypt_token"],
            expires_at=utcnow() - timedelta(hours=1),
        )

        # Clear once
        result1 = clear_secret_and_attachments(db_session, expired_secret.id)
        assert result1 is True

        # Try to clear again
        result2 = clear_secret_and_attachments(db_session, expired_secret.id)
        assert result2 is False
