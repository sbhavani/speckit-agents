"""Contract tests for webhook endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.webhook.auth import WebhookAuth
from src.webhook.server import create_app


@pytest.fixture
def webhook_secret():
    """Test webhook secret."""
    return "test-webhook-secret"


@pytest.fixture
def app(webhook_secret):
    """Create test application."""
    return create_app(
        webhook_secret=webhook_secret,
        command_prefix="/agent-team",
    )


@pytest.fixture
async def client(app):
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
def auth(webhook_secret):
    """Create webhook auth instance."""
    return WebhookAuth(webhook_secret)


class TestWebhookTriggerEndpoint:
    """Contract tests for POST /webhook/trigger endpoint."""

    @pytest.mark.asyncio
    async def test_trigger_with_valid_signature_returns_202(self, client, auth):
        """Test that valid signature returns 202 Accepted."""
        payload = b'{"feature": "Add user authentication"}'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "message" in data

    @pytest.mark.asyncio
    async def test_trigger_without_signature_returns_401(self, client):
        """Test that missing signature returns 401 Unauthorized."""
        payload = b'{"feature": "Add user authentication"}'

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_trigger_with_invalid_signature_returns_401(self, client):
        """Test that invalid signature returns 401 Unauthorized."""
        payload = b'{"feature": "Add user authentication"}'

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": "invalid-signature",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_trigger_with_invalid_json_returns_400(self, client, auth):
        """Test that invalid JSON returns 400 Bad Request."""
        payload = b'not-valid-json'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_without_feature_field_returns_400(self, client, auth):
        """Test that missing feature field returns 400 Bad Request."""
        payload = b'{"project": "test-project"}'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.json()
        # Response may have "detail" or direct body with status/message
        detail = data.get("detail") or data.get("message", "")
        assert "feature" in detail.lower() or "missing" in detail.lower()

    @pytest.mark.asyncio
    async def test_trigger_with_empty_feature_returns_400(self, client, auth):
        """Test that empty feature field returns 400 Bad Request."""
        payload = b'{"feature": ""}'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        # Empty feature should be rejected
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_with_channel_id_header(self, client, auth):
        """Test that X-Channel-ID header is accepted."""
        payload = b'{"feature": "Add feature"}'
        signature = auth.sign_payload(payload)
        channel_id = "test-channel-123"

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
                "X-Channel-ID": channel_id,
            },
        )

        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_trigger_response_includes_message(self, client, auth):
        """Test that response includes human-readable message."""
        payload = b'{"feature": "Test feature"}'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert "message" in data
        assert isinstance(data["message"], str)
        assert len(data["message"]) > 0

    @pytest.mark.asyncio
    async def test_trigger_tampered_payload_returns_401(self, client, auth):
        """Test that tampered payload returns 401."""
        original_payload = b'{"feature": "Add feature"}'
        signature = auth.sign_payload(original_payload)

        # Tamper with the payload
        tampered_payload = b'{"feature": "Remove feature"}'

        response = await client.post(
            "/webhook/trigger",
            content=tampered_payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 401


class TestHealthEndpoint:
    """Contract tests for GET /health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check_returns_200(self, client):
        """Test that health check returns 200 OK."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_health_check_returns_json(self, client):
        """Test that health check returns JSON."""
        response = await client.get("/health")

        assert response.headers["content-type"].startswith("application/json")


class TestSlashCommandEndpoint:
    """Contract tests for POST /command endpoint."""

    @pytest.mark.asyncio
    async def test_suggest_command_returns_in_channel_response(self, client):
        """Test that suggest command returns in_channel response."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team suggest Add new feature",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "in_channel"
        assert "text" in data

    @pytest.mark.asyncio
    async def test_help_command_returns_ephemeral_response(self, client):
        """Test that help command returns ephemeral response."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team help",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"
        assert "text" in data

    @pytest.mark.asyncio
    async def test_unknown_command_returns_ephemeral(self, client):
        """Test that unknown command returns ephemeral error."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team unknowncommand",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"

    @pytest.mark.asyncio
    async def test_suggest_without_args_returns_error(self, client):
        """Test that suggest without args returns error."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team suggest",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"
        assert "usage" in data["text"].lower() or "help" in data["text"].lower()

    @pytest.mark.asyncio
    async def test_help_suggest_returns_command_specific_help(self, client):
        """Test that help with subcommand returns command-specific help."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team help suggest",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"
        assert "suggest" in data["text"].lower()
        assert "usage" in data["text"].lower()

    @pytest.mark.asyncio
    async def test_help_resume_returns_command_specific_help(self, client):
        """Test that help resume returns command-specific help."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team help resume",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"
        assert "resume" in data["text"].lower()
        assert "usage" in data["text"].lower()

    @pytest.mark.asyncio
    async def test_help_unknown_command_returns_error(self, client):
        """Test that help with unknown subcommand returns error."""
        response = await client.post(
            "/command",
            data={
                "command": "/agent-team help unknowncmd",
                "user_id": "user123",
                "channel_id": "channel123",
                "trigger_id": "trigger123",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["response_type"] == "ephemeral"
        assert "unknown" in data["text"].lower()


class TestWebhookContractCompliance:
    """Tests for OpenAPI contract compliance."""

    @pytest.mark.asyncio
    async def test_trigger_endpoint_accepts_json(self, client, auth):
        """Test that trigger endpoint accepts application/json content."""
        payload = b'{"feature": "Test"}'
        signature = auth.sign_payload(payload)

        response = await client.post(
            "/webhook/trigger",
            content=payload,
            headers={
                "X-Webhook-Signature": signature,
                "Content-Type": "application/json",
            },
        )

        assert response.status_code in (200, 201, 202)

    @pytest.mark.asyncio
    async def test_error_response_format(self, client):
        """Test that error responses follow contract format."""
        # No signature - should return 401
        response = await client.post(
            "/webhook/trigger",
            content=b'{"feature": "Test"}',
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401
        # Should return detail about the error
        data = response.json()
        assert "detail" in data
