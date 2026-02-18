"""Redis Streams producer and stream manager."""

import json
import logging
import re
from datetime import datetime
from typing import Optional, Dict, Any

import redis

from redis_streams.connection import RedisConnection
from redis_streams.exceptions import (
    StreamNotFoundError,
    RedisStreamsError,
    PayloadTooLargeError,
    ValidationError,
)
from redis_streams.models import StreamInfo

logger = logging.getLogger(__name__)

# Maximum payload size: 1MB
MAX_PAYLOAD_SIZE = 1024 * 1024

# Stream name validation pattern
STREAM_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class StreamManager:
    """Manages Redis streams - create, delete, inspect."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize StreamManager.

        Args:
            redis_url: Redis connection URL
        """
        self._connection = RedisConnection(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def create_stream(
        self,
        name: str,
        retention_ms: int = 86400000,
        max_length: Optional[int] = None,
    ) -> bool:
        """Create a new stream.

        Args:
            name: Stream name
            retention_ms: Retention time in milliseconds
            max_length: Maximum stream length (optional)

        Returns:
            True if created, False if already exists

        Raises:
            ValidationError: If stream name is invalid
        """
        if not STREAM_NAME_PATTERN.match(name):
            raise ValidationError(
                f"Invalid stream name: {name}. "
                "Use alphanumeric characters, hyphens, and underscores only."
            )

        try:
            # Create stream with a dummy message if it doesn't exist
            self.client.xadd(
                name,
                {"_init": "true"},
                maxlen=1 if max_length else 0,
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Stream exists, that's OK
                return False
            # For other errors, try creating with XGROUP
            try:
                self.client.xgroup_create(name, "init", id="0", mkstream=True)
                return True
            except redis.ResponseError as e2:
                if "BUSYGROUP" in str(e2):
                    return False
                raise RedisStreamsError(f"Failed to create stream: {e2}") from e2

    def delete_stream(self, name: str) -> int:
        """Delete a stream and all its messages.

        Args:
            name: Stream name

        Returns:
            Number of keys deleted (0 or 1)
        """
        return self.client.delete(name)

    def get_stream_info(self, name: str) -> StreamInfo:
        """Get stream information.

        Args:
            name: Stream name

        Returns:
            StreamInfo object

        Raises:
            StreamNotFoundError: If stream doesn't exist
        """
        try:
            info = self.client.xinfo_stream(name)
            return StreamInfo.from_redis(name, info)
        except redis.ResponseError as e:
            if "nonexistent key" in str(e).lower():
                raise StreamNotFoundError(name) from e
            raise RedisStreamsError(f"Failed to get stream info: {e}") from e

    def stream_exists(self, name: str) -> bool:
        """Check if stream exists.

        Args:
            name: Stream name

        Returns:
            True if stream exists
        """
        return self.client.exists(name) > 0

    def get_stream_length(self, name: str) -> int:
        """Get stream length.

        Args:
            name: Stream name

        Returns:
            Number of messages in stream
        """
        try:
            return self.client.xlen(name)
        except redis.ResponseError:
            return 0

    def close(self):
        """Close connection."""
        self._connection.close()


class StreamProducer:
    """Produces events to a Redis stream."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        stream_name: str = "events",
        max_length: int = 10000,
        auto_create_stream: bool = True,
    ):
        """Initialize StreamProducer.

        Args:
            redis_url: Redis connection URL
            stream_name: Name of the stream to produce to
            max_length: Maximum stream length for automatic trimming
            auto_create_stream: Create stream if it doesn't exist
        """
        self._connection = RedisConnection(redis_url)
        self.stream_name = stream_name
        self.max_length = max_length
        self.auto_create_stream = auto_create_stream

        if auto_create_stream:
            manager = StreamManager(redis_url)
            manager.create_stream(stream_name, max_length=max_length)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Publish an event to the stream.

        Args:
            event_type: Event type (e.g., "price.update")
            payload: Event payload (dict, will be JSON serialized)
            metadata: Optional metadata dict

        Returns:
            Redis message ID

        Raises:
            ValidationError: If event_type is empty
            PayloadTooLargeError: If payload exceeds 1MB
            StreamNotFoundError: If stream doesn't exist and auto_create is disabled
        """
        # Validate event_type
        if not event_type or not isinstance(event_type, str):
            raise ValidationError("event_type must be a non-empty string")

        # Serialize payload and check size
        payload_json = json.dumps(payload)
        if len(payload_json) > MAX_PAYLOAD_SIZE:
            raise PayloadTooLargeError(len(payload_json), MAX_PAYLOAD_SIZE)

        # Prepare message
        message = {
            "event_type": event_type,
            "payload": payload_json,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": json.dumps(metadata or {}),
        }

        # Add to stream
        try:
            message_id = self.client.xadd(
                self.stream_name,
                message,
                maxlen=self.max_length,
                approximate=True,  # More efficient trimming
            )
            logger.debug(f"Published event {event_type} with ID {message_id}")
            return message_id
        except redis.ResponseError as e:
            if "nonexistent key" in str(e).lower():
                if self.auto_create_stream:
                    # Try creating stream and retrying
                    self.client.xadd(self.stream_name, {"_init": "true"})
                    message_id = self.client.xadd(
                        self.stream_name,
                        message,
                        maxlen=self.max_length,
                        approximate=True,
                    )
                    return message_id
                raise StreamNotFoundError(self.stream_name) from e
            raise RedisStreamsError(f"Failed to publish event: {e}") from e

    def publish_batch(
        self,
        events: list[dict],
    ) -> list[str]:
        """Publish multiple events in a batch.

        Args:
            events: List of event dicts with 'event_type', 'payload', optional 'metadata'

        Returns:
            List of message IDs
        """
        message_ids = []
        for event in events:
            msg_id = self.publish(
                event_type=event["event_type"],
                payload=event["payload"],
                metadata=event.get("metadata"),
            )
            message_ids.append(msg_id)
        return message_ids

    def close(self):
        """Close connection."""
        self._connection.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
