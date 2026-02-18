"""Redis Streams consumer and consumer group manager."""

import logging
import threading
import time
from typing import Optional, Callable, List, Any, Union

import redis
from redis.exceptions import ResponseError

from redis_streams.connection import RedisConnection
from redis_streams.exceptions import (
    GroupNotFoundError,
    StreamNotFoundError,
    RedisStreamsError,
    ConsumerCrashedError,
)
from redis_streams.models import (
    EventMessage,
    PendingMessage,
    ConsumerGroupInfo,
)
from redis_streams.checkpoint import CheckpointStore, InMemoryCheckpointStore

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
        checkpoint_store: Optional[Union[CheckpointStore, InMemoryCheckpointStore]] = None,
        checkpoint_interval: int = 1,
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
            checkpoint_store: Optional checkpoint store for persistence.
                             If None, checkpointing is disabled.
            checkpoint_interval: Save checkpoint every N messages (default: 1)
        """
        self._connection = RedisConnection(redis_url)
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.block_ms = block_ms
        self.count = count
        self.auto_ack = auto_ack
        self.checkpoint_store = checkpoint_store
        self.checkpoint_interval = checkpoint_interval

        self._running = False
        self._stop_event = threading.Event()
        self._messages_since_checkpoint = 0

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def _ensure_group_exists(self):
        """Ensure consumer group exists."""
        manager = ConsumerGroupManager(self._connection.url)
        manager.create_group(self.stream, self.group, start_id="$")
        manager.close()

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

        # Determine starting position: checkpoint if available, otherwise new messages
        start_id = ">"
        if self.checkpoint_store is not None:
            checkpoint_id = self.checkpoint_store.load(
                self.stream, self.group, self.consumer
            )
            if checkpoint_id:
                # Convert checkpoint to stream ID for reading (add 1 to avoid re-reading)
                start_id = checkpoint_id
                logger.info(
                    f"Resuming from checkpoint {checkpoint_id} for "
                    f"{self.stream}/{self.group}/{self.consumer}"
                )

        logger.info(
            f"Starting consumer {self.consumer} in group {self.group} "
            f"on stream {self.stream} from position {start_id}"
        )

        while self._running:
            try:
                messages = self.client.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer,
                    streams={self.stream: start_id},
                    count=self.count,
                    block=self.block_ms,
                )

                # After first read, switch to ">" to get new messages only
                start_id = ">"

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

            # Save checkpoint if store is configured
            if self.checkpoint_store is not None:
                self._messages_since_checkpoint += 1
                if self._messages_since_checkpoint >= self.checkpoint_interval:
                    self.checkpoint_store.save(
                        self.stream, self.group, self.consumer, message_id
                    )
                    self._messages_since_checkpoint = 0

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

    def get_last_checkpoint(self) -> Optional[str]:
        """Get the last saved checkpoint for this consumer.

        Returns:
            Last checkpoint message ID, or None if no checkpoint
        """
        if self.checkpoint_store is None:
            return None
        return self.checkpoint_store.load(self.stream, self.group, self.consumer)

    def save_checkpoint(self, message_id: str):
        """Manually save checkpoint for current position.

        Args:
            message_id: The message ID to save as checkpoint
        """
        if self.checkpoint_store is not None:
            self.checkpoint_store.save(self.stream, self.group, self.consumer, message_id)
            self._messages_since_checkpoint = 0
            logger.debug(f"Manually saved checkpoint at {message_id}")

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

    def start_reclaim_loop(
        self,
        min_idle_ms: int = 30000,
        interval_seconds: float = 30.0,
    ):
        """Start background thread to reclaim stale messages.

        Args:
            min_idle_ms: Minimum idle time in milliseconds before reclaiming
            interval_seconds: How often to check for stale messages
        """
        def reclaim_worker():
            while self._running:
                try:
                    claimed = self.claim_stale_messages(min_idle_ms)
                    if claimed:
                        logger.info(f"Reclaimed {len(claimed)} stale messages")
                except Exception as e:
                    logger.error(f"Error in reclaim loop: {e}")
                time.sleep(interval_seconds)

        thread = threading.Thread(target=reclaim_worker, daemon=True)
        thread.start()
        logger.info(f"Started reclaim loop with {interval_seconds}s interval")

    def close(self):
        """Gracefully stop consuming and close connection."""
        # Save checkpoint before closing if we have pending messages
        if self.checkpoint_store is not None:
            pending = self.get_pending()
            if pending:
                # Get the last pending message ID to checkpoint
                last_msg = pending[-1]
                self.checkpoint_store.save(
                    self.stream, self.group, self.consumer, last_msg.id
                )
                logger.info(f"Saved checkpoint at {last_msg.id} before closing")

        self._running = False
        self._stop_event.set()
        self._connection.close()

        # Close checkpoint store if it's a Redis-backed store
        if self.checkpoint_store is not None:
            if hasattr(self.checkpoint_store, 'close'):
                self.checkpoint_store.close()

        logger.info(f"Consumer {self.consumer} closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
