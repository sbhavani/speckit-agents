"""Integration test: Event delivery within 500ms.

Tests User Story 1: Real-Time Event Delivery
"""

import time
import threading

import pytest

from redis_streams.producer import StreamProducer, StreamManager
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager


# Test Redis URL - can be overridden with REDIS_URL env var
TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_events"
TEST_GROUP = "test_group"
TEST_CONSUMER = "test_consumer"


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


def test_event_delivery_within_500ms(cleanup):
    """Test that consumer receives event within 500ms of production."""

    # Create consumer in background thread
    received_event = threading.Event()
    received_time = [None]
    event_payload = [None]

    def consumer_callback(event):
        received_time[0] = time.time()
        event_payload[0] = event.payload
        received_event.set()
        return True  # Auto ack

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group=TEST_GROUP,
        consumer=TEST_CONSUMER,
        block_ms=5000,
    )

    # Start consumer in background
    consumer_thread = threading.Thread(target=consumer.subscribe, args=(consumer_callback,))
    consumer_thread.daemon = True
    consumer_thread.start()

    # Wait for consumer to start
    time.sleep(0.5)

    # Produce event and measure time
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    produce_time = time.time()
    payload = {"symbol": "AAPL", "price": 150.25}
    producer.publish(event_type="price.update", payload=payload)
    producer.close()

    # Wait for event with timeout
    timeout = 2.0  # Should receive well within 500ms
    received = received_event.wait(timeout=timeout)

    consumer.close()
    consumer_thread.join(timeout=1.0)

    # Verify delivery
    assert received, "Event was not received within timeout"
    assert received_time[0] is not None

    latency_ms = (received_time[0] - produce_time) * 1000
    print(f"Event delivery latency: {latency_ms:.2f}ms")

    # Verify latency is under 500ms
    assert latency_ms < 500, f"Latency {latency_ms:.2f}ms exceeds 500ms threshold"

    # Verify payload
    assert event_payload[0] == payload


def test_multiple_consumers_independent_receipt(cleanup):
    """Test that multiple consumers independently receive events."""

    # Create two consumers
    consumer1_events = []
    consumer2_events = []
    consumer1_ready = threading.Event()
    consumer2_ready = threading.Event()

    def callback1(event):
        consumer1_events.append(event)
        consumer1_ready.set()
        return True

    def callback2(event):
        consumer2_events.append(event)
        consumer2_ready.set()
        return True

    # Create group and consumers
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, TEST_GROUP, start_id="$")
    manager.close()

    # Start consumers - use DIFFERENT groups so both get the same event
    # (consumer groups split work - each message goes to one consumer)
    c1 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="group_1",  # Different group
        consumer="consumer_1",
        block_ms=5000,
    )

    c2 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="group_2",  # Different group
        consumer="consumer_2",
        block_ms=5000,
    )

    t1 = threading.Thread(target=c1.subscribe, args=(callback1,))
    t2 = threading.Thread(target=c2.subscribe, args=(callback2,))

    t1.daemon = True
    t2.daemon = True
    t1.start()
    t2.start()

    time.sleep(0.5)  # Let consumers connect

    # Publish event
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )
    producer.publish(event_type="test.event", payload={"value": 123})
    producer.close()

    # Wait for both to receive
    consumer1_ready.wait(timeout=2.0)
    consumer2_ready.wait(timeout=2.0)

    c1.close()
    c2.close()

    t1.join(timeout=1.0)
    t2.join(timeout=1.0)

    # Verify both received
    assert len(consumer1_events) > 0, "Consumer 1 did not receive event"
    assert len(consumer2_events) > 0, "Consumer 2 did not receive event"

    # Both should have received the same event
    assert consumer1_events[0].id == consumer2_events[0].id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
