"""Webhook request handlers."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handler for webhook requests."""

    def __init__(self, config: Optional[dict[str, Any]] = None):
        self.config = config or {}
        self.redis = None
        self.redis_url = self.config.get("redis_url", "redis://localhost:6379")
        self.redis_stream = self.config.get("stream", "feature-requests")
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialize Redis connection."""
        try:
            import redis
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            logger.info(f"Webhook handler connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.warning(f"Failed to connect to Redis: {e}. Webhook will work but won't trigger workflows.")
            self.redis = None

    async def handle_trigger(
        self,
        payload: dict[str, Any],
        channel_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Handle workflow trigger request.

        Args:
            payload: Request payload with feature description
            channel_id: Optional Mattermost channel ID

        Returns:
            Response dict with status and message
        """
        feature = payload.get("feature")
        if not feature:
            return {
                "status": "rejected",
                "message": "Missing required field: feature",
            }

        # Publish to Redis stream to trigger workflow
        if self.redis:
            try:
                stream_name = payload.get("stream", self.redis_stream)
                stream_payload = {
                    "command": "suggest",
                    "feature": feature,
                    "channel_id": channel_id or "",
                    "source": "webhook",
                }
                self.redis.xadd(stream_name, stream_payload)
                logger.info(f"Published feature request to Redis: {feature}")
                return {
                    "status": "accepted",
                    "message": f"Workflow started: {feature}",
                }
            except Exception as e:
                logger.error(f"Failed to publish to Redis: {e}")
                return {
                    "status": "rejected",
                    "message": f"Failed to start workflow: {e}",
                }

        # Redis not available - log but don't fail
        logger.info(f"Trigger workflow (no Redis): {feature}")
        return {
            "status": "accepted",
            "message": f"Workflow queued: {feature}",
        }

    async def handle_ping(self) -> dict[str, Any]:
        """Handle ping/health check request.

        Returns:
            Response dict
        """
        return {"status": "ok", "message": "Webhook server is running"}

    async def handle_resume(self, channel_id: Optional[str] = None) -> dict[str, Any]:
        """Handle workflow resume request.

        Args:
            channel_id: Mattermost channel ID

        Returns:
            Response dict with status and message
        """
        # Publish resume command to Redis stream
        if self.redis:
            try:
                stream_payload = {
                    "command": "resume",
                    "channel_id": channel_id or "",
                    "source": "webhook",
                }
                self.redis.xadd(self.redis_stream, stream_payload)
                logger.info(f"Published resume command to Redis")
                return {
                    "status": "accepted",
                    "message": "Resuming workflow...",
                }
            except Exception as e:
                logger.error(f"Failed to publish resume to Redis: {e}")
                return {
                    "status": "rejected",
                    "message": f"Failed to resume workflow: {e}",
                }

        logger.info(f"Resume workflow in channel: {channel_id}")
        return {
            "status": "accepted",
            "message": "Resuming workflow...",
        }

    async def handle_cancel(self, channel_id: Optional[str] = None) -> dict[str, Any]:
        """Handle workflow cancel request.

        Args:
            channel_id: Mattermost channel ID

        Returns:
            Response dict with status and message
        """
        # Publish cancel command to Redis stream to signal orchestrator
        if self.redis:
            try:
                stream_payload = {
                    "command": "cancel",
                    "channel_id": channel_id or "",
                    "source": "webhook",
                }
                self.redis.xadd(self.redis_stream, stream_payload)
                logger.info(f"Published cancel command to Redis for channel: {channel_id}")
                return {
                    "status": "accepted",
                    "message": "Cancelling workflow...",
                }
            except Exception as e:
                logger.error(f"Failed to publish cancel to Redis: {e}")
                return {
                    "status": "rejected",
                    "message": f"Failed to cancel workflow: {e}",
                }

        logger.info(f"Cancel workflow in channel: {channel_id}")
        return {
            "status": "accepted",
            "message": "Cancelling workflow...",
        }

    async def handle_status(self, channel_id: Optional[str] = None) -> dict[str, Any]:
        """Handle workflow status request.

        Args:
            channel_id: Mattermost channel ID

        Returns:
            Response dict with status and message
        """
        # TODO: Query Redis or orchestrator for current workflow status
        logger.info(f"Check status in channel: {channel_id}")
        return {
            "status": "ok",
            "message": "No active workflow",
        }
