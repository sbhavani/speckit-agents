"""Redis Streams consumer and consumer group manager."""

import logging
import threading
import time
from typing import Optional, Callable, List, TYPE_CHECKING

import redis
from redis.exceptions import ResponseError

from redis_streams.connection import RedisConnection
from redis_streams.checkpoint import CheckpointStore
from redis_streams.exceptions import (
    GroupNotFoundError,
    StreamNotFoundError,
    RedisStreamsError,
)
from redis_streams.models import (
    EventMessage,
    PendingMessage,
    ConsumerGroupInfo,
)

logger = logging.getLogger(__name__)


class ConsumerGroupManager:
    """Manages consumer groups for Redis streams."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize ConsumerGroupManager.

        Args:
            redis_url: Redis connection URL
        """
        self._connection = RedisConnection(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def create_group(
        self,
        stream: str,
        group: str,
        start_id: str = "0",
    ) -> bool:
        """Create a consumer group.

        Args:
            stream: Stream name
            group: Consumer group name
            start_id: Starting ID ("0" for all, "$" for new only, or specific ID)

        Returns:
            True if created, False if already exists

        Raises:
            StreamNotFoundError: If stream doesn't exist
        """
        try:
            self.client.xgroup_create(stream, group, id=start_id, mkstream=True)
            return True
        except ResponseError as e:
            error_msg = str(e).upper()
            if "BUSYGROUP" in error_msg:
                # Group already exists, that's OK
                return False
            if "NOGROUP" in error_msg:
                raise GroupNotFoundError(group, stream) from e
            if "ERR" in error_msg and "nonexistent key" in error_msg.lower():
                raise StreamNotFoundError(stream) from e
            raise RedisStreamsError(f"Failed to create group: {e}") from e

    def delete_group(self, stream: str, group: str) -> bool:
        """Delete a consumer group.

        Args:
            stream: Stream name
            group: Consumer group name

        Returns:
            True if deleted
        """
        try:
            self.client.xgroup_destroy(stream, group)
            return True
        except ResponseError as e:
            if "NOGROUP" in str(e).upper():
                return False
            raise RedisStreamsError(f"Failed to delete group: {e}") from e

    def list_groups(self, stream: str) -> List[str]:
        """List all consumer groups for a stream.

        Args:
            stream: Stream name

        Returns:
            List of group names

        Raises:
            StreamNotFoundError: If stream doesn't exist
        """
        try:
            groups = self.client.xinfo_groups(stream)
            return [g["name"] for g in groups]
        except ResponseError as e:
            if "nonexistent key" in str(e).lower():
                raise StreamNotFoundError(stream) from e
            raise RedisStreamsError(f"Failed to list groups: {e}") from e

    def get_group_info(self, stream: str, group: str) -> ConsumerGroupInfo:
        """Get consumer group information.

        Args:
            stream: Stream name
            group: Consumer group name

        Returns:
            ConsumerGroupInfo object

        Raises:
            GroupNotFoundError: If group doesn't exist
        """
        try:
            groups = self.client.xinfo_groups(stream)
            for g in groups:
                if g["name"] == group:
                    return ConsumerGroupInfo.from_redis(stream, group, g)
            raise GroupNotFoundError(group, stream)
        except ResponseError as e:
            if "nonexistent key" in str(e).lower():
                raise StreamNotFoundError(stream) from e
            if "NOGROUP" in str(e).upper():
                raise GroupNotFoundError(group, stream) from e
            raise RedisStreamsError(f"Failed to get group info: {e}") from e

    def close(self):
        """Close connection."""
        self._connection.close()


class StreamConsumer:
    """Consumes events from a Redis stream using consumer groups."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        stream: str = "events",
        group: str = "consumers",
        consumer: str = "consumer-1",
        block_ms: int = 5000,
        count: int = 10,
        auto_ack: bool = False,
        checkpoint_store: Optional[CheckpointStore] = None,
        checkpoint_enabled: bool = True,
    ):
        """Initialize StreamConsumer.

        Args:
            redis_url: Redis connection URL
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name (unique within group)
            block_ms: Blocking timeout in milliseconds
            count: Max messages to fetch at once
            auto_ack: Automatically acknowledge messages after callback
            checkpoint_store: Optional CheckpointStore instance for checkpoint resume.
                             If None and checkpoint_enabled is True, creates default store.
            checkpoint_enabled: Whether to enable checkpoint save/load (default True)
        """
        self._connection = RedisConnection(redis_url)
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.block_ms = block_ms
        self.count = count
        self.auto_ack = auto_ack
        self.checkpoint_enabled = checkpoint_enabled

        # Handle checkpoint store
        self._checkpoint_store_owns_connection = False
        if checkpoint_store is not None:
            self._checkpoint_store = checkpoint_store
        elif checkpoint_enabled:
            # Create default checkpoint store
            self._checkpoint_store = CheckpointStore(redis_url)
            self._checkpoint_store_owns_connection = True
        else:
            self._checkpoint_store = None

        self._running = False
        self._stop_event = threading.Event()

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def _ensure_group_exists(self):
        """Ensure consumer group exists."""
        manager = ConsumerGroupManager(self._connection.url)
        manager.create_group(self.stream, self.group, start_id="$")
        manager.close()

    def _load_checkpoint(self) -> Optional[str]:
        """Load checkpoint for this consumer.

        Returns:
            Checkpoint message ID, or None if no checkpoint exists.
        """
        if not self.checkpoint_enabled or self._checkpoint_store is None:
            return None

        try:
            checkpoint = self._checkpoint_store.load(
                self.stream, self.group, self.consumer
            )
            if checkpoint:
                logger.info(
                    f"Loaded checkpoint {checkpoint} for {self.stream}/"
                    f"{self.group}/{self.consumer}"
                )
            return checkpoint
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def _save_checkpoint(self, message_id: str) -> None:
        """Save checkpoint after message acknowledgment.

        Args:
            message_id: The message ID to save as checkpoint.
        """
        if not self.checkpoint_enabled or self._checkpoint_store is None:
            return

        try:
            self._checkpoint_store.save(
                self.stream, self.group, self.consumer, message_id
            )
            logger.debug(
                f"Saved checkpoint {message_id} for {self.stream}/"
                f"{self.group}/{self.consumer}"
            )
        except Exception as e:
            # Fire-and-forget: log error but don't fail the operation
            logger.warning(f"Failed to save checkpoint: {e}")

    def delete_checkpoint(self) -> None:
        """Delete checkpoint for this consumer.

        Useful for manual reset or forcing reprocessing from the beginning.
        """
        if not self.checkpoint_enabled or self._checkpoint_store is None:
            return

        try:
            self._checkpoint_store.delete(
                self.stream, self.group, self.consumer
            )
            logger.info(
                f"Deleted checkpoint for {self.stream}/"
                f"{self.group}/{self.consumer}"
            )
        except Exception as e:
            logger.warning(f"Failed to delete checkpoint: {e}")

    def get_checkpoint(self) -> Optional[str]:
        """Get current checkpoint position for this consumer.

        Returns:
            Checkpoint message ID, or None if no checkpoint exists.
        """
        if not self.checkpoint_enabled or self._checkpoint_store is None:
            return None

        try:
            return self._checkpoint_store.load(
                self.stream, self.group, self.consumer
            )
        except Exception as e:
            logger.warning(f"Failed to get checkpoint: {e}")
            return None

    def subscribe(
        self,
        callback: Callable[[EventMessage], bool],
        event_types: Optional[List[str]] = None,
    ):
        """Start consuming messages from the stream.

        This is a blocking call that runs until close() is called.

        Args:
            callback: Function to call with each message.
                     Should return True to acknowledge, False to keep pending.
            event_types: Optional list of event types to filter (not yet implemented)

        Raises:
            GroupNotFoundError: If consumer group doesn't exist
        """
        self._ensure_group_exists()
        self._running = True
        self._stop_event.clear()

        # Load checkpoint for resume
        checkpoint_id = self._load_checkpoint()
        stream_position = checkpoint_id if checkpoint_id else ">"

        logger.info(
            f"Starting consumer {self.consumer} in group {self.group} "
            f"on stream {self.stream} from position {stream_position}"
        )

        while self._running:
            try:
                messages = self.client.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer,
                    streams={self.stream: stream_position},
                    count=self.count,
                    block=self.block_ms,
                )

                if not messages:
                    continue

                for stream_name, stream_messages in messages:
                    for msg in stream_messages:
                        message_id = msg[0]
                        values = msg[1]

                        try:
                            event = EventMessage.from_redis(
                                stream_name, message_id, values
                            )

                            # Call the callback
                            should_ack = callback(event)

                            if self.auto_ack or should_ack:
                                self.acknowledge(message_id)

                        except Exception as e:
                            logger.error(f"Error processing message {message_id}: {e}")

            except redis.exceptions.TimeoutError:
                # Normal timeout, continue
                continue
            except redis.exceptions.ConnectionError as e:
                logger.error(f"Connection error: {e}")
                if self._running:
                    time.sleep(1)  # Wait before retrying
                continue
            except Exception as e:
                logger.error(f"Unexpected error in consumer: {e}")
                if self._running:
                    time.sleep(1)

            # Check if we should stop
            if self._stop_event.is_set():
                break

        logger.info(f"Consumer {self.consumer} stopped")

    def acknowledge(self, message_id: str) -> int:
        """Acknowledge a processed message.

        Args:
            message_id: Message ID to acknowledge

        Returns:
            Number of messages acknowledged

        Raises:
            RedisStreamsError: If acknowledgment fails
        """
        try:
            result = self.client.xack(self.stream, self.group, message_id)
            logger.debug(f"Acknowledged message {message_id}")
            # Save checkpoint after successful acknowledgment
            self._save_checkpoint(message_id)
            return result
        except ResponseError as e:
            raise RedisStreamsError(f"Failed to acknowledge message: {e}") from e

    def get_pending(self) -> List[PendingMessage]:
        """Get list of pending (unacknowledged) messages.

        Returns:
            List of PendingMessage objects
        """
        try:
            # Use xpending_range to get pending messages
            # min and max are stream IDs, "-" and "+" mean oldest and newest
            pending = self.client.xpending_range(
                self.stream,
                self.group,
                min="-",
                max="+",
                count=100,
            )
            return [
                PendingMessage.from_redis(self.stream, self.group, p)
                for p in pending
            ]
        except ResponseError as e:
            logger.error(f"Failed to get pending messages: {e}")
            return []

    def get_pending_count(self) -> int:
        """Get count of pending messages for this consumer."""
        pending = self.get_pending()
        return sum(1 for p in pending if p.consumer == self.consumer)

    def claim_stale_messages(
        self,
        min_idle_ms: int = 30000,
    ) -> List[str]:
        """Claim messages that have been idle too long.

        Args:
            min_idle_ms: Minimum idle time in milliseconds

        Returns:
            List of claimed message IDs
        """
        pending = self.get_pending()
        stale = [p.id for p in pending if p.idle_ms >= min_idle_ms]

        if not stale:
            return []

        try:
            claimed = self.client.xclaim(
                self.stream,
                self.group,
                self.consumer,
                min_idle_time=min_idle_ms,
                messages=stale,
            )
            return [msg[0] for msg in claimed]
        except ResponseError as e:
            logger.error(f"Failed to claim stale messages: {e}")
            return []

    def close(self):
        """Gracefully stop consuming and close connection."""
        self._running = False
        self._stop_event.set()
        # Close checkpoint store if we own it
        if self._checkpoint_store_owns_connection and self._checkpoint_store is not None:
            self._checkpoint_store.close()
        self._connection.close()
        logger.info(f"Consumer {self.consumer} closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
