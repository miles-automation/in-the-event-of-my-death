"""Tests for the PoW service functions."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.challenge import Challenge
from app.services.pow_service import cleanup_expired_challenges, generate_challenge
from tests.test_utils import utcnow


def _find_challenge(db_session, challenge_id):
    """Helper: look up a Challenge by ID using select() style."""
    stmt = select(Challenge).where(Challenge.id == challenge_id)
    return db_session.scalars(stmt).first()


@pytest.fixture
def sample_payload_hash():
    """Generate a sample payload hash for testing."""
    return "a" * 64


class TestCleanupExpiredChallenges:
    """Tests for the cleanup_expired_challenges function."""

    def test_cleanup_expired_challenges(self, db_session, sample_payload_hash):
        """Test that expired challenges are deleted."""
        # Create an expired challenge
        challenge = generate_challenge(db_session, sample_payload_hash, 100)

        # Manually set expires_at to the past
        challenge.expires_at = utcnow() - timedelta(minutes=10)
        db_session.commit()

        # Verify it exists
        assert _find_challenge(db_session, challenge.id) is not None

        # Run cleanup
        deleted_count = cleanup_expired_challenges(db_session)

        # Verify it was deleted
        assert deleted_count == 1
        assert _find_challenge(db_session, challenge.id) is None

    def test_cleanup_does_not_delete_valid_challenges(self, db_session, sample_payload_hash):
        """Test that non-expired challenges are not deleted."""
        # Create a valid (non-expired) challenge
        challenge = generate_challenge(db_session, sample_payload_hash, 100)

        # Verify it exists and is not expired
        assert _find_challenge(db_session, challenge.id) is not None
        assert challenge.expires_at > utcnow()

        # Run cleanup
        deleted_count = cleanup_expired_challenges(db_session)

        # Verify it was not deleted
        assert deleted_count == 0
        assert _find_challenge(db_session, challenge.id) is not None

    def test_cleanup_mixed_challenges(self, db_session, sample_payload_hash):
        """Test cleanup with both expired and valid challenges."""
        # Create valid challenge
        valid_challenge = generate_challenge(db_session, sample_payload_hash, 100)
        valid_challenge_id = valid_challenge.id

        # Create expired challenge (need different payload hash for unique nonce)
        expired_challenge = generate_challenge(db_session, "b" * 64, 100)
        expired_challenge_id = expired_challenge.id
        expired_challenge.expires_at = utcnow() - timedelta(minutes=10)
        db_session.commit()

        # Run cleanup
        deleted_count = cleanup_expired_challenges(db_session)

        # Verify only expired was deleted
        assert deleted_count == 1
        assert _find_challenge(db_session, valid_challenge_id) is not None
        assert _find_challenge(db_session, expired_challenge_id) is None

    def test_cleanup_used_but_not_expired_challenges_remain(self, db_session, sample_payload_hash):
        """Test that used but not expired challenges are not deleted."""
        # Create a used but not expired challenge
        challenge = generate_challenge(db_session, sample_payload_hash, 100)
        challenge.is_used = True
        db_session.commit()

        # Run cleanup
        deleted_count = cleanup_expired_challenges(db_session)

        # Verify it was not deleted (cleanup only targets expired, not used)
        assert deleted_count == 0
        assert _find_challenge(db_session, challenge.id) is not None
