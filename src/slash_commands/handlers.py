"""Slash command handlers."""

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    message: str
    response_type: str = "in_channel"  # in_channel or ephemeral


class SlashCommandHandler:
    """Handler for Mattermost slash commands.

    This handler processes slash command requests and coordinates
    with the webhook handler for actual workflow operations.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None):
        """Initialize the slash command handler.

        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self._init_webhook_handler()

    def _init_webhook_handler(self) -> None:
        """Initialize the underlying webhook handler."""
        try:
            from src.webhook.handlers import WebhookHandler
            self.webhook_handler = WebhookHandler(self.config)
        except ImportError:
            logger.warning("Webhook handler not available")
            self.webhook_handler = None

    async def handle_suggest(
        self,
        feature: str,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> CommandResult:
        """Handle the suggest command.

        Args:
            feature: Feature description
            channel_id: Mattermost channel ID
            user_id: User who triggered the command

        Returns:
            CommandResult with success status and message
        """
        if not feature or not feature.strip():
            return CommandResult(
                success=False,
                message="Usage: /agent-team suggest <feature description>",
                response_type="ephemeral",
            )

        if len(feature) > 1000:
            return CommandResult(
                success=False,
                message="Feature description must be under 1000 characters",
                response_type="ephemeral",
            )

        logger.info(
            f"Suggest command: {feature} by user {user_id} in channel {channel_id}"
        )

        if self.webhook_handler:
            result = await self.webhook_handler.handle_trigger(
                {"feature": feature},
                channel_id,
            )
            if result.get("status") == "accepted":
                return CommandResult(
                    success=True,
                    message=f"Starting feature workflow: {feature}",
                )
            return CommandResult(
                success=False,
                message=result.get("message", "Failed to start workflow"),
                response_type="ephemeral",
            )

        return CommandResult(
            success=True,
            message=f"Workflow queued: {feature}",
        )

    async def handle_resume(
        self,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> CommandResult:
        """Handle the resume command.

        Args:
            channel_id: Mattermost channel ID
            user_id: User who triggered the command

        Returns:
            CommandResult with success status and message
        """
        logger.info(f"Resume command by user {user_id} in channel {channel_id}")

        if self.webhook_handler:
            result = await self.webhook_handler.handle_resume(channel_id)
            return CommandResult(
                success=result.get("status") == "accepted",
                message=result.get("message", "Resuming workflow..."),
            )

        return CommandResult(
            success=True,
            message="Resuming workflow...",
        )

    async def handle_cancel(
        self,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> CommandResult:
        """Handle the cancel command.

        Args:
            channel_id: Mattermost channel ID
            user_id: User who triggered the command

        Returns:
            CommandResult with success status and message
        """
        logger.info(f"Cancel command by user {user_id} in channel {channel_id}")

        if self.webhook_handler:
            result = await self.webhook_handler.handle_cancel(channel_id)
            return CommandResult(
                success=result.get("status") == "accepted",
                message=result.get("message", "Cancelling workflow..."),
            )

        return CommandResult(
            success=True,
            message="Cancelling workflow...",
        )

    async def handle_status(
        self,
        channel_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> CommandResult:
        """Handle the status command.

        Args:
            channel_id: Mattermost channel ID
            user_id: User who triggered the command

        Returns:
            CommandResult with success status and message
        """
        logger.info(f"Status command by user {user_id} in channel {channel_id}")

        if self.webhook_handler:
            result = await self.webhook_handler.handle_status(channel_id)
            return CommandResult(
                success=True,
                message=result.get("message", "No active workflow"),
                response_type="ephemeral",
            )

        return CommandResult(
            success=True,
            message="No active workflow",
            response_type="ephemeral",
        )

    async def handle_help(
        self,
        command: Optional[str] = None,
    ) -> CommandResult:
        """Handle the help command.

        Args:
            command: Optional specific command to get help for

        Returns:
            CommandResult with help text
        """
        help_texts = {
            "suggest": "Usage: /agent-team suggest <feature description>\n\n"
            "Start a new feature workflow with the given description.",
            "resume": "Usage: /agent-team resume\n\n"
            "Resume a previously interrupted workflow.",
            "cancel": "Usage: /agent-team cancel\n\n"
            "Cancel a currently running workflow.",
            "status": "Usage: /agent-team status\n\n"
            "Show the current workflow status.",
            "help": "Usage: /agent-team help [command]\n\n"
            "Show help for available commands.",
        }

        if command:
            text = help_texts.get(
                command.lower(),
                f"Unknown command: {command}. Use /agent-team help for available commands.",
            )
        else:
            text = """Available commands:
/agent-team suggest <description> - Start new feature workflow
/agent-team resume - Resume interrupted workflow
/agent-team cancel - Cancel running workflow
/agent-team status - Show workflow status
/agent-team help [command] - Show this message"""

        return CommandResult(
            success=True,
            message=text,
            response_type="ephemeral",
        )
