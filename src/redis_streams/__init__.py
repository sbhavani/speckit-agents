# Redis Streams Event-Driven Architecture
#
# A library for building event-driven systems using Redis Streams.
# Provides producer and consumer utilities with consumer group support.
#
# Key features:
# - Real-time event delivery with sub-500ms latency
# - Consumer group support for multiple concurrent consumers
# - Checkpoint/resume for failure recovery
# - At-least-once delivery guarantees

from redis_streams.producer import StreamProducer, StreamManager
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager
from redis_streams.models import EventMessage, PendingMessage
from redis_streams.checkpoint import CheckpointStore, InMemoryCheckpointStore
from redis_streams.exceptions import (
    RedisStreamsError,
    StreamNotFoundError,
    GroupNotFoundError,
    PayloadTooLargeError,
    ConsumerCrashedError,
)

__version__ = "0.1.0"

__all__ = [
    "StreamProducer",
    "StreamManager",
    "StreamConsumer",
    "ConsumerGroupManager",
    "EventMessage",
    "PendingMessage",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "RedisStreamsError",
    "StreamNotFoundError",
    "GroupNotFoundError",
    "PayloadTooLargeError",
    "ConsumerCrashedError",
]
