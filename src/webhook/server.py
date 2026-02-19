"""FastAPI webhook server."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import yaml

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.webhook.auth import WebhookAuth
from src.webhook.handlers import WebhookHandler

logger = logging.getLogger(__name__)


class SlashCommandPayload(BaseModel):
    """Mattermost slash command payload."""

    command: str
    trigger_id: str = ""
    user_id: str
    channel_id: str
    team_id: str = ""
    response_url: str = ""


class SlashCommandResponse(BaseModel):
    """Response for slash command."""

    response_type: str = "in_channel"  # in_channel or ephemeral
    text: str
    username: Optional[str] = None
    icon_url: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting webhook server")
    yield
    logger.info("Shutting down webhook server")


def create_app(
    webhook_secret: str = "",
    command_prefix: str = "/agent-team",
    host: str = "0.0.0.0",
    port: int = 8080,
    config: Optional[dict[str, Any]] = None,
) -> FastAPI:
    """Create and configure the FastAPI webhook application.

    Args:
        webhook_secret: HMAC secret for webhook authentication
        command_prefix: Slash command prefix (default: /agent-team)
        host: Server host
        port: Server port
        config: Additional configuration

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="Agent Team Webhook Server",
        description="HTTP webhook endpoint for triggering feature workflows",
        version="1.0.0",
        lifespan=lifespan,
    )

    auth = WebhookAuth(webhook_secret) if webhook_secret else None
    handler = WebhookHandler(config)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return await handler.handle_ping()

    @app.get("/help")
    async def help_endpoint():
        """Help endpoint that returns information about available commands."""
        return {
            "commands": [
                {
                    "name": "suggest",
                    "description": "Start a new feature workflow",
                    "usage": f"{command_prefix} suggest <feature description>",
                    "example": f"{command_prefix} suggest Add user authentication",
                },
                {
                    "name": "resume",
                    "description": "Resume a previously interrupted workflow",
                    "usage": f"{command_prefix} resume",
                    "example": f"{command_prefix} resume",
                },
                {
                    "name": "cancel",
                    "description": "Cancel a currently running workflow",
                    "usage": f"{command_prefix} cancel",
                    "example": f"{command_prefix} cancel",
                },
                {
                    "name": "status",
                    "description": "Show the current workflow status",
                    "usage": f"{command_prefix} status",
                    "example": f"{command_prefix} status",
                },
                {
                    "name": "help",
                    "description": "Show help information",
                    "usage": f"{command_prefix} help [command]",
                    "example": f"{command_prefix} help suggest",
                },
            ],
            "webhook": {
                "trigger": {
                    "url": "/webhook/trigger",
                    "method": "POST",
                    "description": "Trigger a new feature workflow via webhook",
                    "auth": "HMAC-SHA256 signature in X-Webhook-Signature header",
                    "payload": {
                        "feature": "Description of the feature (required)",
                        "project": "Project name (optional)",
                        "channel_id": "Mattermost channel ID (optional)",
                    },
                },
                "cancel": {
                    "url": "/webhook/cancel",
                    "method": "POST",
                    "description": "Cancel a running feature workflow via webhook",
                    "auth": "HMAC-SHA256 signature in X-Webhook-Signature header",
                    "payload": {
                        "channel_id": "Mattermost channel ID (optional)",
                    },
                },
            },
            "command_prefix": command_prefix,
        }

    @app.post("/webhook/trigger")
    async def trigger_workflow(request: Request):
        """Trigger a new feature workflow via webhook."""
        # Audit log the request
        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            f"AUDIT: Webhook trigger request from {client_ip}",
            extra={
                "event_type": "webhook_trigger",
                "client_ip": client_ip,
                "path": "/webhook/trigger",
            },
        )

        if not auth:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook server not configured",
            )

        # Verify signature
        body = await request.body()
        signature = request.headers.get("X-Webhook-Signature")
        if not auth.verify_signature(body, signature):
            logger.warning(
                f"AUDIT: Invalid webhook signature from {client_ip}",
                extra={
                    "event_type": "webhook_trigger_failed",
                    "client_ip": client_ip,
                    "reason": "invalid_signature",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

        # Parse and validate payload
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload",
            )

        channel_id = request.headers.get("X-Channel-ID")
        feature = payload.get("feature", "")

        # Audit log the command invocation
        logger.info(
            f"AUDIT: Command invocation - trigger workflow: {feature}",
            extra={
                "event_type": "command_invocation",
                "command": "trigger",
                "feature": feature,
                "channel_id": channel_id,
                "source": "webhook",
            },
        )

        result = await handler.handle_trigger(payload, channel_id)

        if result["status"] == "rejected":
            logger.warning(
                f"AUDIT: Command rejected - trigger: {feature}",
                extra={
                    "event_type": "command_rejected",
                    "command": "trigger",
                    "feature": feature,
                    "reason": result.get("message", ""),
                },
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result,
            )

        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)

    @app.post("/webhook/cancel")
    async def cancel_workflow(request: Request):
        """Cancel a running feature workflow via webhook."""
        # Audit log the request
        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            f"AUDIT: Webhook cancel request from {client_ip}",
            extra={
                "event_type": "webhook_cancel",
                "client_ip": client_ip,
                "path": "/webhook/cancel",
            },
        )

        if not auth:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook server not configured",
            )

        # Verify signature
        body = await request.body()
        signature = request.headers.get("X-Webhook-Signature")
        if not auth.verify_signature(body, signature):
            logger.warning(
                f"AUDIT: Invalid webhook signature from {client_ip}",
                extra={
                    "event_type": "webhook_cancel_failed",
                    "client_ip": client_ip,
                    "reason": "invalid_signature",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

        # Parse optional payload
        try:
            payload = await request.json() if body else {}
        except Exception:
            payload = {}

        channel_id = request.headers.get("X-Channel-ID") or payload.get("channel_id")
        result = await handler.handle_cancel(channel_id)

        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)

    @app.post("/command")
    async def handle_slash_command(request: Request):
        """Handle Mattermost slash command callback.

        Mattermost sends POST requests with form-urlencoded data.
        Response must be JSON within 3 seconds.
        """
        # Parse form data from Mattermost
        form_data = await request.form()
        payload = dict(form_data)

        command = payload.get("command", "")
        user_id = payload.get("user_id", "")
        channel_id = payload.get("channel_id", "")
        trigger_id = payload.get("trigger_id", "")

        # Audit log the slash command invocation
        logger.info(
            f"AUDIT: Slash command invocation - {command}",
            extra={
                "event_type": "slash_command",
                "command": command,
                "user_id": user_id,
                "channel_id": channel_id,
                "trigger_id": trigger_id,
            },
        )

        # Import parser here to avoid circular imports
        from src.slash_commands.parser import CommandParser

        parser = CommandParser(prefix=command_prefix)
        parsed = parser.parse(command)

        if not parsed:
            logger.warning(
                f"AUDIT: Unknown slash command - {command}",
                extra={
                    "event_type": "slash_command_unknown",
                    "command": command,
                    "user_id": user_id,
                    "channel_id": channel_id,
                },
            )
            return SlashCommandResponse(
                response_type="ephemeral",
                text=f"Unknown command. Use {command_prefix} help for available commands.",
            )

        # Validate arguments
        is_valid, error_msg = parser.validate_args(parsed.command, parsed.args)
        if not is_valid:
            logger.warning(
                f"AUDIT: Invalid slash command args - {parsed.command}: {error_msg}",
                extra={
                    "event_type": "slash_command_invalid_args",
                    "command": parsed.command,
                    "command_args": parsed.args,
                    "error": error_msg,
                    "user_id": user_id,
                    "channel_id": channel_id,
                },
            )
            return SlashCommandResponse(
                response_type="ephemeral",
                text=error_msg,
            )

        # Audit log the valid command invocation
        logger.info(
            f"AUDIT: Executing slash command - {parsed.command}",
            extra={
                "event_type": "slash_command_executed",
                "command": parsed.command,
                "command_args": parsed.args,
                "user_id": user_id,
                "channel_id": channel_id,
            },
        )

        # Handle each command
        if parsed.command == "help":
            return await _handle_help(parser, parsed.subcommand)
        elif parsed.command == "suggest":
            return await _handle_suggest(handler, parsed.args, channel_id)
        elif parsed.command == "resume":
            return await _handle_resume(handler, channel_id)
        elif parsed.command == "cancel":
            return await _handle_cancel(handler, channel_id)
        elif parsed.command == "status":
            return await _handle_status(handler, channel_id)
        else:
            return SlashCommandResponse(
                response_type="ephemeral",
                text=f"Unknown command: {parsed.command}",
            )

    return app


async def _handle_help(parser, subcommand: str = None) -> SlashCommandResponse:
    """Handle help command."""
    if subcommand:
        # Command-specific help
        help_texts = {
            "suggest": f"Usage: {parser.prefix} suggest <feature description>\n\nStart a new feature workflow with the given description.",
            "resume": f"Usage: {parser.prefix} resume\n\nResume a previously interrupted workflow.",
            "cancel": f"Usage: {parser.prefix} cancel\n\nCancel a currently running workflow.",
            "status": f"Usage: {parser.prefix} status\n\nShow the current workflow status.",
        }
        text = help_texts.get(subcommand, f"Unknown command: {subcommand}")
    else:
        # General help
        text = f"""Available commands:
{parser.prefix} suggest <description> - Start new feature workflow
{parser.prefix} resume - Resume interrupted workflow
{parser.prefix} cancel - Cancel running workflow
{parser.prefix} status - Show workflow status
{parser.prefix} help [command] - Show this message"""

    return SlashCommandResponse(response_type="ephemeral", text=text)


async def _handle_suggest(handler: WebhookHandler, args: str, channel_id: str) -> SlashCommandResponse:
    """Handle suggest command."""
    result = await handler.handle_trigger({"feature": args}, channel_id)
    if result["status"] == "accepted":
        return SlashCommandResponse(
            response_type="in_channel",
            text=f"Starting feature workflow: {args}",
        )
    return SlashCommandResponse(
        response_type="ephemeral",
        text=result.get("message", "Failed to start workflow"),
    )


async def _handle_resume(handler: WebhookHandler, channel_id: str) -> SlashCommandResponse:
    """Handle resume command."""
    result = await handler.handle_resume(channel_id)
    return SlashCommandResponse(
        response_type="in_channel",
        text=result.get("message", "Resuming workflow..."),
    )


async def _handle_cancel(handler: WebhookHandler, channel_id: str) -> SlashCommandResponse:
    """Handle cancel command."""
    result = await handler.handle_cancel(channel_id)
    return SlashCommandResponse(
        response_type="in_channel",
        text=result.get("message", "Cancelling workflow..."),
    )


async def _handle_status(handler: WebhookHandler, channel_id: str) -> SlashCommandResponse:
    """Handle status command."""
    result = await handler.handle_status(channel_id)
    return SlashCommandResponse(
        response_type="ephemeral",
        text=result.get("message", "Checking status..."),
    )


def main():
    """Run the webhook server directly."""
    import uvicorn

    # Load config from yaml
    config_path = "config.yaml"
    if Path("config.local.yaml").exists():
        config_path = "config.local.yaml"

    config = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    # Extract webhook and redis config
    webhook_cfg = config.get("webhook", {})
    redis_cfg = config.get("redis_streams", {})

    handler_config = {
        "redis_url": redis_cfg.get("url", "redis://localhost:6379"),
        "stream": redis_cfg.get("stream", "feature-requests"),
    }

    app = create_app(
        webhook_secret=webhook_cfg.get("secret", "development-secret"),
        command_prefix="/agent-team",
        host=webhook_cfg.get("host", "0.0.0.0"),
        port=webhook_cfg.get("port", 8080),
        config=handler_config,
    )
    uvicorn.run(app, host=webhook_cfg.get("host", "0.0.0.0"), port=webhook_cfg.get("port", 8080))


if __name__ == "__main__":
    main()
