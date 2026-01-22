"""Tests for the feedback endpoint and Matrix notification service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.matrix_service import send_feedback_notification


class TestFeedbackEndpoint:
    """Integration tests for POST /api/v1/feedback."""

    def test_submit_feedback_success(self, client):
        """Test submitting feedback successfully."""
        with patch(
            "app.routers.feedback.send_feedback_notification", new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = True

            response = client.post(
                "/api/v1/feedback",
                json={"message": "This is test feedback with enough characters."},
            )

            assert response.status_code == 201
            data = response.json()
            assert data["success"] is True
            assert "Thank you" in data["message"]
            mock_notify.assert_called_once()

    def test_submit_feedback_with_email(self, client):
        """Test submitting feedback with optional email."""
        with patch(
            "app.routers.feedback.send_feedback_notification", new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = True

            response = client.post(
                "/api/v1/feedback",
                json={
                    "message": "This is test feedback with enough characters.",
                    "email": "test@example.com",
                },
            )

            assert response.status_code == 201
            mock_notify.assert_called_once_with(
                message="This is test feedback with enough characters.",
                email="test@example.com",
            )

    def test_submit_feedback_message_too_short(self, client):
        """Test validation error for message too short."""
        response = client.post(
            "/api/v1/feedback",
            json={"message": "Short"},
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_submit_feedback_message_too_long(self, client):
        """Test validation error for message too long."""
        response = client.post(
            "/api/v1/feedback",
            json={"message": "x" * 2001},
        )

        assert response.status_code == 422

    def test_submit_feedback_invalid_email(self, client):
        """Test validation error for invalid email format."""
        response = client.post(
            "/api/v1/feedback",
            json={
                "message": "This is test feedback with enough characters.",
                "email": "not-an-email",
            },
        )

        assert response.status_code == 422

    def test_submit_feedback_empty_email_is_ok(self, client):
        """Test that empty string email is treated as None."""
        with patch(
            "app.routers.feedback.send_feedback_notification", new_callable=AsyncMock
        ) as mock_notify:
            mock_notify.return_value = True

            response = client.post(
                "/api/v1/feedback",
                json={
                    "message": "This is test feedback with enough characters.",
                    "email": "",
                },
            )

            assert response.status_code == 201
            # Email should be passed as None
            mock_notify.assert_called_once_with(
                message="This is test feedback with enough characters.",
                email=None,
            )


class TestMatrixNotificationService:
    """Unit tests for send_feedback_notification."""

    @pytest.mark.asyncio
    async def test_notification_success(self):
        """Test successful Matrix notification."""
        with patch("app.services.matrix_service.settings") as mock_settings:
            mock_settings.matrix_homeserver_url = "https://chat.sparkswarm.com"
            mock_settings.matrix_access_token = "test-token"
            mock_settings.matrix_room_id = "!testroom:chat.sparkswarm.com"

            with patch("app.services.matrix_service.httpx.AsyncClient") as mock_client:
                mock_response = AsyncMock()
                mock_response.raise_for_status = AsyncMock()
                mock_client.return_value.__aenter__.return_value.put = AsyncMock(
                    return_value=mock_response
                )

                result = await send_feedback_notification(
                    message="Test message", email="test@example.com"
                )

                assert result is True

    @pytest.mark.asyncio
    async def test_notification_not_configured(self):
        """Test when Matrix is not configured."""
        with patch("app.services.matrix_service.settings") as mock_settings:
            mock_settings.matrix_homeserver_url = None
            mock_settings.matrix_access_token = None
            mock_settings.matrix_room_id = None

            result = await send_feedback_notification(message="Test message", email=None)

            assert result is False

    @pytest.mark.asyncio
    async def test_notification_failure_does_not_raise(self):
        """Test that API failure doesn't raise exception."""
        from unittest.mock import MagicMock

        import httpx

        with patch("app.services.matrix_service.settings") as mock_settings:
            mock_settings.matrix_homeserver_url = "https://chat.sparkswarm.com"
            mock_settings.matrix_access_token = "test-token"
            mock_settings.matrix_room_id = "!testroom:chat.sparkswarm.com"

            with patch("app.services.matrix_service.httpx.AsyncClient") as mock_client:
                # Create a proper mock response that raises on raise_for_status
                mock_request = MagicMock()
                mock_response = MagicMock()
                mock_response.status_code = 500

                def raise_for_status():
                    raise httpx.HTTPStatusError(
                        "Server error", request=mock_request, response=mock_response
                    )

                mock_response.raise_for_status = raise_for_status

                mock_client.return_value.__aenter__.return_value.put = AsyncMock(
                    return_value=mock_response
                )

                # Should not raise, just return False
                result = await send_feedback_notification(message="Test message", email=None)

                assert result is False
