"""Integration test: Consumer join with configurable start position.

Tests User Story 2: Multiple Concurrent Consumers
"""

import time
import threading

import pytest

from redis_streams.producer import StreamProducer, StreamManager
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager


# Test Redis URL - can be overridden with REDIS_URL env var
TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_join_stream"
TEST_GROUP = "test_join_group"


@pytest.fixture
def cleanup():
    """Clean up test stream before and after tests."""
    manager = StreamManager(TEST_REDIS_URL)
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


def test_consumer_receives_from_beginning(cleanup):
    """Test that new consumer with start_id='0' receives all existing messages."""

    # First, produce some events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Publish several events before consumer joins
    for i in range(5):
        producer.publish(event_type="prejoin.event", payload={"index": i})

    producer.close()

    # Now create consumer group with start_id="0" (from beginning)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="0")
    manager.close()

    # Create and start consumer
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        ready_event.set()
        return True  # Auto ack

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_from_beginning",
        block_ms=5000,
    )

    thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    thread.daemon = True
    thread.start()

    # Wait for events
    ready_event.wait(timeout=2.0)
    consumer.close()
    thread.join(timeout=1.0)

    # Verify consumer received all 5 pre-join events
    assert len(received_events) >= 5, (
        f"Expected at least 5 events, got {len(received_events)}"
    )


def test_consumer_receives_new_only(cleanup):
    """Test that new consumer with start_id='$' receives only new messages."""

    # Create consumer group with start_id="$" (new only)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="$")
    manager.close()

    # Now produce events AFTER consumer group is created
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Publish events after group creation
    for i in range(3):
        producer.publish(event_type="postjoin.event", payload={"index": i})

    producer.close()

    # Create and start consumer
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        if len(received_events) >= 3:
            ready_event.set()
        return True  # Auto ack

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_new_only",
        block_ms=5000,
    )

    thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    thread.daemon = True
    thread.start()

    # Wait for events
    ready_event.wait(timeout=2.0)
    consumer.close()
    thread.join(timeout=1.0)

    # Verify consumer received all 3 post-join events
    assert len(received_events) == 3, (
        f"Expected 3 events, got {len(received_events)}"
    )


def test_consumer_join_with_specific_id(cleanup):
    """Test that consumer can join from a specific message ID."""

    # First, produce events and capture their IDs
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Publish events and capture IDs
    ids = []
    for i in range(3):
        msg_id = producer.publish(event_type="ordered.event", payload={"index": i})
        ids.append(msg_id)

    producer.close()

    # Create consumer group starting from second message
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    start_id = ids[1]  # Start from second message
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id=start_id)
    manager.close()

    # Create and start consumer
    received_events = []
    ready_event = threading.Event()

    def callback(event):
        received_events.append(event)
        if len(received_events) >= 2:
            ready_event.set()
        return True  # Auto ack

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer="consumer_from_id",
        block_ms=5000,
    )

    thread = threading.Thread(target=consumer.subscribe, args=(callback,))
    thread.daemon = True
    thread.start()

    # Wait for events
    ready_event.wait(timeout=2.0)
    consumer.close()
    thread.join(timeout=1.0)

    # Verify consumer skipped first message and received messages 2 and 3
    assert len(received_events) >= 2, (
        f"Expected at least 2 events, got {len(received_events)}"
    )
    # Should not receive the first message
    first_ids = [e.id for e in received_events]
    assert ids[0] not in first_ids, "First message should have been skipped"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
