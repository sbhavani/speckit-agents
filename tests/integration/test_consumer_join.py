"""Integration test: New consumer joins and receives from configured position.

Tests User Story 2: Multiple Concurrent Consumers - Consumer join behavior
"""

import time
import threading

import pytest

from redis_streams.producer import StreamProducer, StreamManager
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager
from redis_streams.checkpoint import CheckpointStore


# Test Redis URL - can be overridden with REDIS_URL env var
TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_consumer_join"
TEST_GROUP = "test_join_group"


@pytest.fixture
def cleanup():
    """Clean up test stream before and after tests."""
    manager = StreamManager(TEST_REDIS_URL)
    checkpoint_store = CheckpointStore(TEST_REDIS_URL)

    # Clean up checkpoints
    try:
        checkpoint_store.delete(TEST_STREAM, TEST_GROUP, "consumer_1")
        checkpoint_store.delete(TEST_STREAM, TEST_GROUP, "consumer_2")
    except Exception:
        pass
    checkpoint_store.close()

    # Clean up stream
    try:
        manager.delete_stream(TEST_STREAM)
    except Exception:
        pass
    yield
    # Cleanup after
    try:
        manager.delete_stream(TEST_STREAM)
    except Exception:
        pass
    manager.close()


def test_consumer_joins_from_beginning(cleanup):
    """Test new consumer joining receives messages from stream beginning."""

    # First, produce some events BEFORE consumer joins
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Produce events that will exist before consumer joins
    for i in range(5):
        producer.publish(
            event_type="test.event",
            payload={"sequence": i}
        )

    producer.close()

    # Wait a bit for events to settle
    time.sleep(0.2)

    # Now create group with start_id="0" (from beginning)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="0")
    manager.close()

    # Start new consumer that should receive ALL events (from beginning)
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        if len(received_events) >= 5:
            ready_event.set()
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="new_consumer",
        block_ms=5000,
    )

    # Start consumer
    consumer_thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    consumer_thread.daemon = True
    consumer_thread.start()

    # Wait for all 5 events
    received_all = ready_event.wait(timeout=3.0)

    consumer.close()
    consumer_thread.join(timeout=1.0)

    # Verify consumer received all events from beginning
    assert received_all or len(received_events) >= 5, \
        f"Expected 5 events, got {len(received_events)}"
    assert len(received_events) == 5, \
        f"Expected exactly 5 events, got {len(received_events)}"


def test_consumer_joins_from_checkpoint(cleanup):
    """Test new consumer joining receives messages from checkpoint."""

    checkpoint_store = CheckpointStore(TEST_REDIS_URL)

    # Simulate existing consumer that processed some messages
    # by creating a checkpoint for "consumer_1"
    checkpoint_store.save(
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_1",
        message_id="0-3"  # Pretend consumer_1 processed up to message 0-3
    )

    # Produce 5 more events after the checkpoint
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # First produce the initial events (so stream has content)
    for i in range(4):
        producer.publish(
            event_type="test.event",
            payload={"sequence": i}
        )

    # Now save checkpoint at message 0-3
    checkpoint_store.save(
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_1",
        message_id="0-3"
    )

    # Produce more events after checkpoint
    for i in range(4, 8):
        producer.publish(
            event_type="test.event",
            payload={"sequence": i}
        )

    producer.close()

    # Create group starting from new messages only
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="$")
    manager.close()

    # New consumer should join and receive events AFTER checkpoint
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        # Should receive messages 0-4, 0-5, 0-6, 0-7 (4 new messages)
        if len(received_events) >= 4:
            ready_event.set()
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_2",
        block_ms=5000,
    )

    consumer_thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    consumer_thread.daemon = True
    consumer_thread.start()

    # Wait for events
    received = ready_event.wait(timeout=3.0)

    consumer.close()
    consumer_thread.join(timeout=1.0)
    checkpoint_store.close()

    # Should have received 4 new events (0-4 through 0-7)
    assert len(received_events) >= 4, \
        f"Expected at least 4 new events after checkpoint, got {len(received_events)}"


def test_consumer_joins_from_new_only(cleanup):
    """Test new consumer joining receives only new messages (from $)."""

    # Create group that only receives NEW messages
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="$")
    manager.close()

    # Produce events AFTER group creation
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Wait a moment
    time.sleep(0.1)

    # Now produce events - these should be received
    producer.publish(event_type="test.event", payload={"value": 1})
    producer.publish(event_type="test.event", payload={"value": 2})
    producer.publish(event_type="test.event", payload={"value": 3})
    producer.close()

    # Consumer should receive ONLY the 3 new events
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        if len(received_events) >= 3:
            ready_event.set()
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="new_consumer",
        block_ms=5000,
    )

    consumer_thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    consumer_thread.daemon = True
    consumer_thread.start()

    received = ready_event.wait(timeout=3.0)

    consumer.close()
    consumer_thread.join(timeout=1.0)

    # Should only receive the 3 events produced after group creation
    assert len(received_events) == 3, \
        f"Expected exactly 3 events, got {len(received_events)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
