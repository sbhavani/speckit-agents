"""Checkpoint storage for consumer position tracking."""

import logging
from typing import Dict, Optional

import redis

from redis_streams.connection import RedisConnection

logger = logging.getLogger(__name__)


class CheckpointStore:
    """Stores consumer checkpoint positions."""

    # Key prefix for checkpoints
    KEY_PREFIX = "redis_streams:checkpoint"

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """Initialize CheckpointStore.

        Args:
            redis_url: Redis connection URL
        """
        self._connection = RedisConnection(redis_url)

    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        return self._connection.client

    def _make_key(self, stream: str, group: str, consumer: str) -> str:
        """Generate Redis key for checkpoint."""
        return f"{self.KEY_PREFIX}:{stream}:{group}:{consumer}"

    def save(
        self,
        stream: str,
        group: str,
        consumer: str,
        message_id: str,
    ):
        """Save checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name
            message_id: Last processed message ID
        """
        key = self._make_key(stream, group, consumer)
        self.client.set(key, message_id)
        logger.debug(f"Saved checkpoint {message_id} for {stream}/{group}/{consumer}")

    def load(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> Optional[str]:
        """Load checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name

        Returns:
            Last processed message ID, or None if no checkpoint
        """
        key = self._make_key(stream, group, consumer)
        message_id = self.client.get(key)
        if message_id:
            logger.debug(
                f"Loaded checkpoint {message_id} for {stream}/{group}/{consumer}"
            )
        return message_id

    def delete(
        self,
        stream: str,
        group: str,
        consumer: str,
    ):
        """Delete checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name
        """
        key = self._make_key(stream, group, consumer)
        self.client.delete(key)
        logger.debug(f"Deleted checkpoint for {stream}/{group}/{consumer}")

    def get_all_for_group(
        self,
        stream: str,
        group: str,
    ) -> Dict[str, str]:
        """Get all checkpoints for a consumer group.

        Args:
            stream: Stream name
            group: Consumer group name

        Returns:
            Dict mapping consumer name to last message ID
        """
        pattern = f"{self.KEY_PREFIX}:{stream}:{group}:*"
        keys = self.client.keys(pattern)

        checkpoints = {}
        for key in keys:
            consumer = key.split(":")[-1]
            message_id = self.client.get(key)
            if message_id:
                checkpoints[consumer] = message_id

        return checkpoints

    def close(self):
        """Close connection."""
        self._connection.close()


class InMemoryCheckpointStore:
    """In-memory checkpoint storage (for MVP/testing)."""

    def __init__(self):
        """Initialize in-memory store."""
        self._checkpoints: Dict[str, str] = {}

    def _make_key(self, stream: str, group: str, consumer: str) -> str:
        """Generate key for checkpoint."""
        return f"{stream}:{group}:{consumer}"

    def save(
        self,
        stream: str,
        group: str,
        consumer: str,
        message_id: str,
    ):
        """Save checkpoint for a consumer."""
        key = self._make_key(stream, group, consumer)
        self._checkpoints[key] = message_id
        logger.debug(f"Saved checkpoint {message_id} for {stream}/{group}/{consumer}")

    def load(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> Optional[str]:
        """Load checkpoint for a consumer."""
        key = self._make_key(stream, group, consumer)
        return self._checkpoints.get(key)

    def delete(
        self,
        stream: str,
        group: str,
        consumer: str,
    ):
        """Delete checkpoint for a consumer."""
        key = self._make_key(stream, group, consumer)
        self._checkpoints.pop(key, None)

    def get_all_for_group(
        self,
        stream: str,
        group: str,
    ) -> Dict[str, str]:
        """Get all checkpoints for a consumer group."""
        prefix = f"{stream}:{group}:"
        return {
            k.split(":")[-1]: v
            for k, v in self._checkpoints.items()
            if k.startswith(prefix)
        }

    def close(self):
        """Close connection (no-op for in-memory store)."""
        pass
