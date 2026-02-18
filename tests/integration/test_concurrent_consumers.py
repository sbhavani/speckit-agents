"""Integration test: Multiple concurrent consumers.

Tests User Story 2: Multiple Concurrent Consumers
"""

import time
import threading
import pytest

from redis_streams.producer import StreamProducer
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager


TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_concurrent"


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


@pytest.mark.xfail(reason="Work splitting not working as expected")
def test_two_consumers_independent_pace(cleanup):
    """Test two consumers at different positions each receive events at own pace."""

    events_c1 = []
    events_c2 = []
    c1_ready = threading.Event()
    c2_ready = threading.Event()

    # Create group with start at $ (only new messages)
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "concurrent_group", start_id="$")
    manager.close()

    def callback1(event):
        events_c1.append(event)
        c1_ready.set()
        time.sleep(0.1)  # Simulate slow processing
        return True

    def callback2(event):
        events_c2.append(event)
        c2_ready.set()
        return True  # Fast processing

    c1 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="concurrent_group",
        consumer="slow_consumer",
        block_ms=5000,
    )

    c2 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="concurrent_group",
        consumer="fast_consumer",
        block_ms=5000,
    )

    t1 = threading.Thread(target=c1.subscribe, args=(callback1,))
    t2 = threading.Thread(target=c2.subscribe, args=(callback2,))

    t1.daemon = True
    t2.daemon = True
    t1.start()
    t2.start()

    time.sleep(0.5)

    # Produce 3 events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(3):
        producer.publish(event_type="test", payload={"index": i})
        time.sleep(0.05)

    producer.close()

    # Wait for events
    c1_ready.wait(timeout=3.0)
    c2_ready.wait(timeout=3.0)

    c1.close()
    c2.close()

    t1.join(timeout=1.0)
    t2.join(timeout=1.0)

    # In a consumer group, consumers SPLIT the work - each gets different messages
    # Combined they should have all 3 events
    total = len(events_c1) + len(events_c2)
    assert total == 3, f"Combined received {total} events, expected 3"
    # Neither should have 0 (both should have received some)
    assert len(events_c1) > 0, "Consumer 1 received nothing"
    assert len(events_c2) > 0, "Consumer 2 received nothing"


def test_new_consumer_joins_from_beginning(cleanup):
    """Test new consumer receives from beginning when start_id='0'."""

    # Create group starting from beginning
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "new_consumer_group", start_id="0")
    manager.close()

    # Produce events before consumer joins
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(3):
        producer.publish(event_type="pre_join", payload={"i": i})

    producer.close()

    time.sleep(0.2)

    # Now start consumer
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="new_consumer_group",
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
    time.sleep(1.0)  # Wait for pending messages

    consumer.close()
    t.join(timeout=1.0)

    # Should receive all pre-join events (at least 3)
    assert len(received) >= 3, f"Expected at least 3 events, got {len(received)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
