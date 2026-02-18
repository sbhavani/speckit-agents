"""Redis Streams consumer and consumer group manager."""

import logging
import threading
import time
from typing import Optional, Callable, List, Any, Union

import redis
from redis.exceptions import ResponseError

from redis_streams.connection import RedisConnection
from redis_streams.checkpoint import CheckpointStore, InMemoryCheckpointStore
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
        use_checkpoint: bool = True,
        reclaim_interval_ms: int = 0,
        reclaim_min_idle_ms: int = 30000,
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
            checkpoint_store: Checkpoint store for persisting consumer position.
                              If None and use_checkpoint is True, uses Redis-based store.
            use_checkpoint: Whether to persist/checkpoint consumer position
            reclaim_interval_ms: Interval in ms for reclaim loop (0 = disabled)
            reclaim_min_idle_ms: Min idle time in ms to claim stale messages
        """
        self._connection = RedisConnection(redis_url)
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.block_ms = block_ms
        self.count = count
        self.auto_ack = auto_ack
        self.use_checkpoint = use_checkpoint
        self.reclaim_interval_ms = reclaim_interval_ms
        self.reclaim_min_idle_ms = reclaim_min_idle_ms

        # Initialize checkpoint store
        if checkpoint_store is not None:
            self._checkpoint_store = checkpoint_store
        elif use_checkpoint:
            self._checkpoint_store = CheckpointStore(redis_url)
        else:
            self._checkpoint_store = None

        # For retry with exponential backoff
        self._base_retry_delay = 1.0
        self._max_retry_delay = 30.0

        self._running = False
        self._stop_event = threading.Event()
        self._reclaim_thread: Optional[threading.Thread] = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def _ensure_group_exists(self, start_id: str = "$"):
        """Ensure consumer group exists and optionally resume from checkpoint.

        Args:
            start_id: Starting ID for new consumers ("0" for all, "$" for new only)
        """
        # Try to resume from checkpoint
        checkpoint = None
        if self._checkpoint_store and self.use_checkpoint:
            checkpoint = self._checkpoint_store.load(self.stream, self.group, self.consumer)
            if checkpoint:
                start_id = checkpoint
                logger.info(f"Resuming from checkpoint: {checkpoint}")

        manager = ConsumerGroupManager(self._connection.url)
        manager.create_group(self.stream, self.group, start_id=start_id)
        manager.close()

    def _start_reclaim_loop(self):
        """Start the reclaim loop in a background thread."""
        if self.reclaim_interval_ms <= 0:
            return

        def reclaim_worker():
            while self._running:
                try:
                    claimed = self.claim_stale_messages(self.reclaim_min_idle_ms)
                    if claimed:
                        logger.info(f"Claimed {len(claimed)} stale messages")
                except Exception as e:
                    logger.error(f"Error in reclaim loop: {e}")

                # Sleep for the interval
                self._stop_event.wait(timeout=self.reclaim_interval_ms / 1000.0)

        self._reclaim_thread = threading.Thread(target=reclaim_worker, daemon=True)
        self._reclaim_thread.start()
        logger.info(f"Started reclaim loop with interval {self.reclaim_interval_ms}ms")

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

        # Start reclaim loop if configured
        self._start_reclaim_loop()

        logger.info(
            f"Starting consumer {self.consumer} in group {self.group} "
            f"on stream {self.stream}"
        )

        retry_delay = self._base_retry_delay

        while self._running:
            try:
                messages = self.client.xreadgroup(
                    groupname=self.group,
                    consumername=self.consumer,
                    streams={self.stream: ">"},
                    count=self.count,
                    block=self.block_ms,
                )

                # Reset retry delay on successful read
                retry_delay = self._base_retry_delay

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
                    logger.info(f"Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    # Exponential backoff
                    retry_delay = min(retry_delay * 2, self._max_retry_delay)
                continue
            except Exception as e:
                logger.error(f"Unexpected error in consumer: {e}")
                if self._running:
                    logger.info(f"Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, self._max_retry_delay)

            # Check if we should stop
            if self._stop_event.is_set():
                break

        logger.info(f"Consumer {self.consumer} stopped")

    def acknowledge(self, message_id: str) -> int:
        """Acknowledge a processed message and persist checkpoint.

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

            # Persist checkpoint after acknowledgment
            if self._checkpoint_store and self.use_checkpoint:
                self._checkpoint_store.save(
                    self.stream, self.group, self.consumer, message_id
                )

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

        # Wait for reclaim thread to finish
        if self._reclaim_thread and self._reclaim_thread.is_alive():
            self._reclaim_thread.join(timeout=2.0)

        # Close checkpoint store if we own it
        if self._checkpoint_store and isinstance(
            self._checkpoint_store, CheckpointStore
        ):
            self._checkpoint_store.close()

        self._connection.close()
        logger.info(f"Consumer {self.consumer} closed")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
