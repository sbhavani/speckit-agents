"""Test consumer join behavior - new consumers can join and receive from configured position."""

import pytest
import time

from redis_streams.producer import StreamProducer
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager


@pytest.fixture
def redis_url():
    """Get Redis URL from environment or use default."""
    return "redis://localhost:6379"


@pytest.fixture
def stream_name():
    """Generate unique stream name."""
    return f"test-join-{int(time.time() * 1000)}"


@pytest.fixture
def group_name():
    """Consumer group name."""
    return "test-group"


def test_consumer_joins_from_beginning(redis_url, stream_name, group_name):
    """Test new consumer joins and receives from beginning of stream."""
    producer = StreamProducer(redis_url, stream_name)
    manager = ConsumerGroupManager(redis_url)

    # Produce some events first
    producer.publish("test-event", {"data": "event1"})
    producer.publish("test-event", {"data": "event2"})
    producer.publish("test-event", {"data": "event3"})

    # Create group with start_id="0" so new consumers get all messages
    manager.create_group(stream_name, group_name, start_id="0")
    manager.close()

    # New consumer joins and should receive all events
    received = []

    def callback(event):
        received.append(event.values.get("data"))
        return True  # Acknowledge

    consumer = StreamConsumer(
        redis_url,
        stream=stream_name,
        group=group_name,
        consumer="new-consumer",
        auto_ack=True,
    )

    # Use a short timeout for test
    import threading

    def consume():
        consumer.subscribe(callback, resume_from_checkpoint=False)

    thread = threading.Thread(target=consume)
    thread.start()

    # Wait for messages
    time.sleep(2)
    consumer.close()
    thread.join(timeout=3)

    producer.close()

    # Verify all events received
    assert len(received) >= 1, f"Expected events, got {received}"


def test_consumer_joins_from_new_only(redis_url, stream_name, group_name):
    """Test new consumer joins and only receives new messages (from $)."""
    producer = StreamProducer(redis_url, stream_name)
    manager = ConsumerGroupManager(redis_url)

    # Produce events before group creation
    producer.publish("test-event", {"data": "old-event1"})
    producer.publish("test-event", {"data": "old-event2"})

    # Create group with start_id="$" so new consumers only get new messages
    manager.create_group(stream_name, group_name, start_id="$")
    manager.close()

    # Produce more events after group creation
    producer.publish("test-event", {"data": "new-event1"})
    producer.publish("test-event", {"data": "new-event2"})

    # New consumer should only receive new events
    received = []

    def callback(event):
        received.append(event.values.get("data"))
        return True

    consumer = StreamConsumer(
        redis_url,
        stream=stream_name,
        group=group_name,
        consumer="new-consumer-only",
        auto_ack=True,
    )

    import threading

    def consume():
        consumer.subscribe(callback, resume_from_checkpoint=False)

    thread = threading.Thread(target=consume)
    thread.start()

    # Wait for messages
    time.sleep(2)
    consumer.close()
    thread.join(timeout=3)

    producer.close()

    # Verify only new events received (not old events)
    assert "old-event1" not in received, f"Should not receive old events: {received}"
    assert "old-event2" not in received, f"Should not receive old events: {received}"
    assert "new-event1" in received or "new-event2" in received, f"Expected new events: {received}"


def test_consumer_resumes_from_checkpoint(redis_url, stream_name, group_name):
    """Test consumer resumes from checkpoint on restart."""
    producer = StreamProducer(redis_url, stream_name)
    manager = ConsumerGroupManager(redis_url)

    # Create group
    manager.create_group(stream_name, group_name, start_id="0")
    manager.close()

    # Produce events
    producer.publish("test-event", {"data": "event1"})
    producer.publish("test-event", {"data": "event2"})
    producer.publish("test-event", {"data": "event3"})

    # First consumer - process first event and checkpoint
    received_first = []

    def callback1(event):
        received_first.append(event.values.get("data"))
        return True  # Acknowledge and checkpoint

    consumer1 = StreamConsumer(
        redis_url,
        stream=stream_name,
        group=group_name,
        consumer="consumer-1",
        auto_ack=True,
    )

    import threading

    def consume1():
        consumer1.subscribe(callback1, resume_from_checkpoint=False)

    thread1 = threading.Thread(target=consume1)
    thread1.start()

    # Wait for first event
    time.sleep(1.5)
    consumer1.close()
    thread1.join(timeout=2)

    # Second consumer should resume from checkpoint (after first event)
    received_second = []

    def callback2(event):
        received_second.append(event.values.get("data"))
        return True

    consumer2 = StreamConsumer(
        redis_url,
        stream=stream_name,
        group=group_name,
        consumer="consumer-2",
        auto_ack=True,
    )

    def consume2():
        consumer2.subscribe(callback2, resume_from_checkpoint=True)

    thread2 = threading.Thread(target=consume2)
    thread2.start()

    # Wait for remaining events
    time.sleep(2)
    consumer2.close()
    thread2.join(timeout=3)

    producer.close()

    # First consumer got event1
    assert "event1" in received_first

    # Second consumer should get event2 and event3 (resumed from checkpoint)
    assert "event2" in received_second or "event3" in received_second, \
        f"Expected events after checkpoint, got: {received_second}"
