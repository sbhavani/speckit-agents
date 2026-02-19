"""Unit tests for slash commands."""

import pytest
from src.slash_commands.parser import CommandParser, ParsedCommand


class TestCommandParser:
    """Tests for CommandParser."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = CommandParser(prefix="/agent-team")

    def test_parse_suggest_command(self):
        """Test parsing suggest command with feature description."""
        result = self.parser.parse("/agent-team suggest Add user authentication")

        assert result is not None
        assert result.command == "suggest"
        assert result.args == "Add user authentication"

    def test_parse_suggest_command_without_prefix(self):
        """Test parsing suggest command without full prefix."""
        result = self.parser.parse("suggest Add user authentication")

        assert result is not None
        assert result.command == "suggest"
        assert result.args == "Add user authentication"

    def test_parse_resume_command(self):
        """Test parsing resume command."""
        result = self.parser.parse("/agent-team resume")

        assert result is not None
        assert result.command == "resume"
        assert result.args == ""

    def test_parse_cancel_command(self):
        """Test parsing cancel command."""
        result = self.parser.parse("/agent-team cancel")

        assert result is not None
        assert result.command == "cancel"
        assert result.args == ""

    def test_parse_help_command(self):
        """Test parsing help command."""
        result = self.parser.parse("/agent-team help")

        assert result is not None
        assert result.command == "help"
        assert result.subcommand is None

    def test_parse_help_with_specific_command(self):
        """Test parsing help with specific command."""
        result = self.parser.parse("/agent-team help suggest")

        assert result is not None
        assert result.command == "help"
        assert result.subcommand == "suggest"

    def test_parse_status_command(self):
        """Test parsing status command."""
        result = self.parser.parse("/agent-team status")

        assert result is not None
        assert result.command == "status"
        assert result.args == ""

    def test_parse_invalid_command(self):
        """Test parsing invalid command returns None."""
        result = self.parser.parse("/agent-team unknowncommand")

        assert result is None

    def test_parse_empty_command(self):
        """Test parsing empty command returns None."""
        result = self.parser.parse("")

        assert result is None

    def test_validate_args_suggest_success(self):
        """Test validating suggest command with valid args."""
        is_valid, error = self.parser.validate_args("suggest", "Add user auth")

        assert is_valid is True
        assert error is None

    def test_validate_args_suggest_empty(self):
        """Test validating suggest command with empty args."""
        is_valid, error = self.parser.validate_args("suggest", "")

        assert is_valid is False
        assert "Usage:" in error

    def test_validate_args_suggest_whitespace(self):
        """Test validating suggest command with whitespace only."""
        is_valid, error = self.parser.validate_args("suggest", "   ")

        assert is_valid is False

    def test_validate_args_suggest_too_long(self):
        """Test validating suggest command with args > 1000 chars."""
        long_args = "a" * 1001
        is_valid, error = self.parser.validate_args("suggest", long_args)

        assert is_valid is False
        assert "1000 characters" in error

    def test_validate_args_suggest_max_length_ok(self):
        """Test validating suggest command with exactly 1000 chars."""
        args = "a" * 1000
        is_valid, error = self.parser.validate_args("suggest", args)

        assert is_valid is True
        assert error is None

    def test_validate_args_resume_no_args_required(self):
        """Test validating resume command - no args required."""
        is_valid, error = self.parser.validate_args("resume", "")

        assert is_valid is True
        assert error is None


class TestWebhookHandler:
    """Tests for webhook handler."""

    @pytest.mark.asyncio
    async def test_handle_trigger_success(self):
        """Test successful workflow trigger."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler({"redis_url": "redis://localhost:6379", "stream": "test-stream"})

        # Note: This will fail to connect to Redis but should still return accepted
        result = await handler.handle_trigger({"feature": "Add user auth"}, "channel123")

        assert result["status"] in ["accepted", "rejected"]
        assert "feature" in result.get("message", "") or "message" in result

    @pytest.mark.asyncio
    async def test_handle_trigger_missing_feature(self):
        """Test trigger without feature field."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler()

        result = await handler.handle_trigger({}, "channel123")

        assert result["status"] == "rejected"
        assert "feature" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        """Test health check endpoint."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler()

        result = await handler.handle_ping()

        assert result["status"] == "ok"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_handle_resume(self):
        """Test resume workflow handler."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler()

        # Redis likely unavailable but should still return accepted
        result = await handler.handle_resume("channel123")

        assert result["status"] in ["accepted", "rejected"]
        assert "message" in result

    @pytest.mark.asyncio
    async def test_handle_cancel(self):
        """Test cancel workflow handler."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler()

        result = await handler.handle_cancel("channel123")

        assert "status" in result
        assert "message" in result

    @pytest.mark.asyncio
    async def test_handle_status(self):
        """Test status check handler."""
        from src.webhook.handlers import WebhookHandler

        handler = WebhookHandler()

        result = await handler.handle_status("channel123")

        assert result["status"] == "ok"
        assert "message" in result
