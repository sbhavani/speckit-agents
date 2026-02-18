"""Checkpoint persistence contracts.

These define the expected API contracts for checkpoint functionality.
"""

from typing import Optional, Dict
from abc import ABC, abstractmethod


class CheckpointStoreInterface(ABC):
    """Abstract interface for checkpoint storage."""

    @abstractmethod
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
            message_id: Message ID to save
            monotonic: Only save if greater than existing

        Returns:
            True if saved, False if skipped
        """
        pass

    @abstractmethod
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
            Message ID or None if no checkpoint
        """
        pass

    @abstractmethod
    def validate(self, message_id: str) -> bool:
        """Validate checkpoint format.

        Args:
            message_id: Message ID to validate

        Returns:
            True if valid Redis message ID format
        """
        pass


class CheckpointAwareConsumerInterface(ABC):
    """Abstract interface for consumers with checkpoint support."""

    @abstractmethod
    def load_checkpoint(self) -> Optional[str]:
        """Load checkpoint from store.

        Returns:
            Last checkpoint message ID or None
        """
        pass

    @abstractmethod
    def acknowledge(self, message_id: str) -> int:
        """Acknowledge message and save checkpoint.

        Args:
            message_id: Message ID to acknowledge

        Returns:
            Number of messages acknowledged
        """
        pass
