"""Integration test: Failure recovery and backpressure.

Tests User Story 4: Failure Recovery and Backpressure Handling
"""

import time
import threading
import pytest

from redis_streams.producer import StreamProducer
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager
from redis_streams.monitoring import StreamMonitor, LagMonitor


TEST_REDIS_URL = "redis://localhost:6379"
TEST_STREAM = "test_recovery"


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


def test_offline_consumer_catches_up(cleanup):
    """Test offline consumer reconnects and catches up from checkpoint."""

    # Create group
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "recovery_group", start_id="$")
    manager.close()

    # Producer publishes events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(10):
        producer.publish(event_type="recovery", payload={"index": i})

    producer.close()

    time.sleep(0.3)

    # Consumer starts and processes first 5, then "dies" (closes)
    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="recovery_group",
        consumer="recovery_consumer",
        block_ms=1000,
        auto_ack=False,
    )

    processed_first = []

    def callback1(event):
        processed_first.append(event.payload.get("index"))
        if event.payload.get("index", 0) < 5:
            consumer.acknowledge(event.id)
        return True

    ready1 = threading.Event()

    def run1():
        ready1.set()
        consumer.subscribe(callback1)

    t1 = threading.Thread(target=run1)
    t1.daemon = True
    t1.start()

    ready1.wait(timeout=2.0)
    time.sleep(1.5)

    # Kill consumer (simulating crash)
    consumer.close()
    t1.join(timeout=1.0)

    # Check pending - should have 5 unacknowledged
    consumer2 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="recovery_group",
        consumer="recovery_consumer",
        block_ms=1000,
    )

    pending = consumer2.get_pending()
    consumer2.close()

    print(f"Pending after first consumer: {len(pending)}")
    assert len(pending) == 5, f"Expected 5 pending, got {len(pending)}"


def test_backpressure_detection(cleanup):
    """Test backpressure signal when consumer lags."""

    # Create group
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "backpressure_group", start_id="$")
    manager.close()

    # Produce many events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(100):
        producer.publish(event_type="backpressure", payload={"index": i})

    producer.close()

    time.sleep(0.3)

    # Check backpressure metrics
    monitor = StreamMonitor(TEST_REDIS_URL)
    metrics = monitor.get_backpressure_metrics(TEST_STREAM, "backpressure_group")
    monitor.close()

    print(f"Stream length: {metrics.stream_length}")
    print(f"Pending: {metrics.pending_count}")
    print(f"Healthy: {metrics.is_healthy}")


def test_lag_monitor(cleanup):
    """Test consumer lag monitoring."""

    # Create group and consumer
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "lag_group", start_id="$")
    manager.close()

    # Produce events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(10):
        producer.publish(event_type="lag", payload={"index": i})

    producer.close()

    time.sleep(0.3)

    # Check lag
    lag_monitor = LagMonitor(TEST_REDIS_URL)
    lags = lag_monitor.get_all_consumer_lags(TEST_STREAM, "lag_group")
    lag_monitor.close()

    print(f"Consumer lags: {lags}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
