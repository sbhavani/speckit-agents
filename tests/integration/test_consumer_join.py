"""Integration test: New consumer joins and receives from configured position.

Tests User Story 2: Multiple Concurrent Consumers - Consumer join behavior
"""

import time
import threading
import pytest

from redis_streams.producer import StreamProducer
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager


TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_consumer_join"


@pytest.fixture
def cleanup():
    """Clean up test stream."""
    from redis_streams.producer import StreamManager
    manager = StreamManager(TEST_REDIS_URL)
    try:
        manager.delete_stream(TEST_STREAM)
    except Exception:
        pass
    yield
    try:
        manager.delete_stream(TEST_STREAM)
    except Exception:
        pass
    manager.close()


def test_consumer_joins_from_beginning(cleanup):
    """Test new consumer receives events from beginning when start_id='0'."""

    # Create group starting from beginning (all existing messages)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "join_group", start_id="0")
    manager.close()

    # Produce events before consumer joins
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(5):
        producer.publish(event_type="pre_join", payload={"index": i})

    producer.close()

    time.sleep(0.3)

    # Now start consumer - should receive ALL pre-existing events
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="join_group",
        consumer="late_joiner",
        block_ms=3000,
    )

    ready = threading.Event()

    def run_consumer():
        ready.set()
        consumer.subscribe(callback)

    t = threading.Thread(target=run_consumer)
    t.daemon = True
    t.start()

    ready.wait(timeout=2.0)
    time.sleep(1.5)  # Wait for pending messages to be delivered

    consumer.close()
    t.join(timeout=1.0)

    # Should receive all pre-join events (exactly 5)
    assert len(received) >= 5, f"Expected at least 5 events, got {len(received)}"
    # Verify event types
    event_types = [e.event_type for e in received]
    assert all(et == "pre_join" for et in event_types), "Unexpected event types"


def test_consumer_joins_from_new_only(cleanup):
    """Test new consumer receives only new events when start_id='$'."""

    # Create group starting from $ (only new messages)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "new_only_group", start_id="$")
    manager.close()

    # Produce events BEFORE consumer starts
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(3):
        producer.publish(event_type="pre_join", payload={"index": i})

    producer.close()

    time.sleep(0.2)

    # Start consumer - should NOT receive pre-join events
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="new_only_group",
        consumer="new_consumer",
        block_ms=2000,
    )

    ready = threading.Event()

    def run_consumer():
        ready.set()
        consumer.subscribe(callback)

    t = threading.Thread(target=run_consumer)
    t.daemon = True
    t.start()

    ready.wait(timeout=2.0)
    time.sleep(0.5)

    # Now produce events AFTER consumer started
    producer2 = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(2):
        producer2.publish(event_type="post_join", payload={"index": i})

    producer2.close()

    time.sleep(1.0)  # Wait for post-join events

    consumer.close()
    t.join(timeout=1.0)

    # Should NOT receive pre-join events, only post-join
    assert len(received) >= 2, f"Expected at least 2 events, got {len(received)}"
    event_types = [e.event_type for e in received]
    assert all(et == "post_join" for et in event_types), \
        f"Expected only post_join events, got {event_types}"


def test_consumer_joins_from_specific_id(cleanup):
    """Test new consumer receives events from a specific message ID."""

    # First, create stream and get initial message ID
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    # Publish first batch
    msg_id_1 = producer.publish(event_type="batch1", payload={"index": 0})
    producer.close()

    time.sleep(0.1)

    # Publish second batch
    producer2 = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    msg_id_2 = producer2.publish(event_type="batch2", payload={"index": 1})
    producer2.publish(event_type="batch2", payload={"index": 2})
    producer2.close()

    time.sleep(0.1)

    # Create group starting from the second message ID
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "specific_id_group", start_id=msg_id_2)
    manager.close()

    # Consumer should receive messages from msg_id_2 onwards (batch2 events only)
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="specific_id_group",
        consumer="specific_consumer",
        block_ms=3000,
    )

    ready = threading.Event()

    def run_consumer():
        ready.set()
        consumer.subscribe(callback)

    t = threading.Thread(target=run_consumer)
    t.daemon = True
    t.start()

    ready.wait(timeout=2.0)
    time.sleep(1.0)

    consumer.close()
    t.join(timeout=1.0)

    # Should only receive batch2 events (skip batch1)
    assert len(received) >= 2, f"Expected at least 2 events, got {len(received)}"
    event_types = [e.event_type for e in received]
    assert all(et == "batch2" for et in event_types), \
        f"Expected only batch2 events, got {event_types}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
