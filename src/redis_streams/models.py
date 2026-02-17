"""Data models for Redis Streams."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import json


@dataclass
class EventMessage:
    """Represents an event message from a stream."""

    id: str
    stream: str
    event_type: str
    payload: dict
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_redis(cls, stream: str, message_id: str, values: dict) -> "EventMessage":
        """Create EventMessage from Redis message format.

        Args:
            stream: Stream name
            message_id: Redis message ID
            values: Message values dict

        Returns:
            EventMessage instance
        """
        return cls(
            id=message_id,
            stream=stream,
            event_type=values.get("event_type", ""),
            payload=json.loads(values.get("payload", "{}")),
            timestamp=values.get("timestamp", datetime.utcnow().isoformat()),
            metadata=json.loads(values.get("metadata", "{}")),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": json.dumps(self.payload),
            "metadata": json.dumps(self.metadata),
        }


@dataclass
class PendingMessage:
    """Represents a pending (unacknowledged) message."""

    id: str
    consumer: str
    idle_ms: int
    delivered: int
    stream: str = ""
    group: str = ""

    @classmethod
    def from_redis(
        cls, stream: str, group: str, pending: dict
    ) -> "PendingMessage":
        """Create PendingMessage from Redis XPENDING format.

        Args:
            stream: Stream name
            group: Consumer group name
            pending: Pending entry from XPENDING

        Returns:
            PendingMessage instance
        """
        return cls(
            id=pending["message_id"],
            consumer=pending["consumer"],
            idle_ms=pending["time_since_delivered"],
            delivered=pending["delivery_counter"],
            stream=stream,
            group=group,
        )


@dataclass
class StreamInfo:
    """Stream information."""

    name: str
    length: int
    first_entry_id: Optional[str] = None
    last_entry_id: Optional[str] = None
    groups: int = 0
    created_ms: Optional[int] = None

    @classmethod
    def from_redis(cls, name: str, info: dict) -> "StreamInfo":
        """Create StreamInfo from Redis XINFO STREAMS output."""
        return cls(
            name=name,
            length=info.get("length", 0),
            first_entry_id=info.get("first-entry-id"),
            last_entry_id=info.get("last-entry-id"),
            groups=info.get("groups", 0),
            created_ms=info.get("created-at"),
        )


@dataclass
class ConsumerGroupInfo:
    """Consumer group information."""

    name: str
    stream: str
    consumers: int
    pending: int
    last_delivered_id: str = ""

    @classmethod
    def from_redis(cls, stream: str, group: str, info: dict) -> "ConsumerGroupInfo":
        """Create ConsumerGroupInfo from Redis XINFO GROUPS output."""
        return cls(
            name=group,
            stream=stream,
            consumers=info.get("consumers", 0),
            pending=info.get("pending", 0),
            last_delivered_id=info.get("last-delivered-id", ""),
        )


@dataclass
class ConsumerInfo:
    """Consumer information."""

    name: str
    group: str
    stream: str
    pending: int
    idle_ms: int

    @classmethod
    def from_redis(
        cls, stream: str, group: str, consumer: str, info: dict
    ) -> "ConsumerInfo":
        """Create ConsumerInfo from Redis XINFO GROUPS output."""
        return cls(
            name=consumer,
            group=group,
            stream=stream,
            pending=info.get("pending", 0),
            idle_ms=info.get("idle", 0),
        )
