"""Checkpoint storage for consumer position tracking."""

import logging
import re
import time
from typing import Dict, Optional

import redis

from redis_streams.connection import RedisConnection

logger = logging.getLogger(__name__)

# Redis message ID format: timestamp-sequence (e.g., "1234567890-0")
MESSAGE_ID_PATTERN = re.compile(r"^\d+-\d+$")

# Retry configuration
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.1  # 100ms


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
        monotonic: bool = True,
    ) -> bool:
        """Save checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name
            message_id: Last processed message ID
            monotonic: Only save if greater than existing (default True)

        Returns:
            True if saved, False if skipped (monotonic check failed)
        """
        key = self._make_key(stream, group, consumer)

        # Monotonic check: only save if new ID > existing
        if monotonic:
            existing = self.client.get(key)
            if existing and existing >= message_id:
                logger.debug(
                    f"Skipping checkpoint {message_id} - not greater than existing {existing}"
                )
                return False

        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                self.client.set(key, message_id)
                logger.debug(f"Saved checkpoint {message_id} for {stream}/{group}/{consumer}")
                return True
            except redis.RedisError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Failed to save checkpoint (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to save checkpoint after {MAX_RETRIES} attempts: {e}")

        logger.error(f"Checkpoint save failed after {MAX_RETRIES} attempts: {last_error}")
        return False

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

        # Retry logic with exponential backoff
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                message_id = self.client.get(key)
                if message_id:
                    # Validate loaded checkpoint
                    if not self.validate(message_id):
                        logger.warning(f"Invalid checkpoint format: {message_id}")
                        return None
                    logger.debug(
                        f"Loaded checkpoint {message_id} for {stream}/{group}/{consumer}"
                    )
                return message_id
            except redis.RedisError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Failed to load checkpoint (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"Failed to load checkpoint after {MAX_RETRIES} attempts: {e}")

        logger.error(f"Checkpoint load failed after {MAX_RETRIES} attempts: {last_error}")
        return None

    def validate(self, message_id: str) -> bool:
        """Validate checkpoint format.

        Args:
            message_id: Message ID to validate

        Returns:
            True if valid Redis message ID format
        """
        if not message_id:
            return False
        return MESSAGE_ID_PATTERN.match(str(message_id)) is not None

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
        monotonic: bool = True,
    ) -> bool:
        """Save checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name
            message_id: Last processed message ID
            monotonic: Only save if greater than existing (default True)

        Returns:
            True if saved, False if skipped (monotonic check failed)
        """
        key = self._make_key(stream, group, consumer)

        # Monotonic check: only save if new ID > existing
        if monotonic:
            existing = self._checkpoints.get(key)
            if existing and existing >= message_id:
                logger.debug(
                    f"Skipping checkpoint {message_id} - not greater than existing {existing}"
                )
                return False

        self._checkpoints[key] = message_id
        logger.debug(f"Saved checkpoint {message_id} for {stream}/{group}/{consumer}")
        return True

    def load(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> Optional[str]:
        """Load checkpoint for a consumer."""
        key = self._make_key(stream, group, consumer)
        message_id = self._checkpoints.get(key)
        if message_id and not self.validate(message_id):
            logger.warning(f"Invalid checkpoint format: {message_id}")
            return None
        return message_id

    def validate(self, message_id: str) -> bool:
        """Validate checkpoint format.

        Args:
            message_id: Message ID to validate

        Returns:
            True if valid Redis message ID format
        """
        if not message_id:
            return False
        return MESSAGE_ID_PATTERN.match(str(message_id)) is not None

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
