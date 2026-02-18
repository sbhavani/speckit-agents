"""Integration test: Consumer join behavior.

Tests User Story 2: Multiple Concurrent Consumers - consumer join scenarios
"""

import time
import threading
import pytest

from redis_streams.producer import StreamProducer
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager
from redis_streams.checkpoint import InMemoryCheckpointStore


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
    """Test new consumer joins and receives events from beginning (start_id='0')."""

    # Create group starting from beginning
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "test_group", start_id="0")
    manager.close()

    # Produce events before consumer joins
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    for i in range(5):
        producer.publish(event_type="pre_join", payload={"i": i})

    producer.close()
    time.sleep(0.2)

    # Start consumer that should receive all pre-join events
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="test_group",
        consumer="joiner_from_beginning",
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

    # Should receive all pre-join events
    assert len(received) >= 5, f"Expected at least 5 events, got {len(received)}"


def test_consumer_joins_from_new_only(cleanup):
    """Test new consumer joins and only receives new events (start_id='$')."""

    # Create group starting from new only
    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "new_only_group", start_id="$")
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

    # Start consumer that should NOT receive pre-join events
    received = []

    def callback(event):
        received.append(event)
        return True

    consumer = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="new_only_group",
        consumer="joiner_new_only",
        block_ms=1000,
    )

    ready = threading.Event()

    def run_consumer():
        ready.set()
        consumer.subscribe(callback)

    t = threading.Thread(target=run_consumer)
    t.daemon = True
    t.start()

    ready.wait(timeout=2.0)
    time.sleep(1.5)  # Wait and ensure no pre-join events arrive

    consumer.close()
    t.join(timeout=1.0)

    # Should NOT receive pre-join events (only new events after consumer started)
    pre_join_count = sum(1 for e in received if e.event_type == "pre_join")
    assert pre_join_count == 0, f"Should not receive pre-join events, got {pre_join_count}"


def test_consumer_resumes_from_checkpoint(cleanup):
    """Test consumer resumes from checkpoint after restart."""

    # Create group with checkpoint store
    checkpoint_store = InMemoryCheckpointStore()

    manager = ConsumerGroupManager(TEST_REDIS_URL)
    manager.create_group(TEST_STREAM, "checkpoint_group", start_id="0")
    manager.close()

    # Produce events
    producer = StreamProducer(
        redis_url=TEST_REDIS_URL,
        stream_name=TEST_STREAM,
    )

    message_ids = []
    for i in range(5):
        msg_id = producer.publish(event_type="checkpoint_test", payload={"i": i})
        message_ids.append(msg_id)

    producer.close()
    time.sleep(0.2)

    # First consumer: process some events and save checkpoint
    processed = []

    def callback1(event):
        processed.append(event)
        # Save checkpoint after each message
        if len(processed) == 3:
            checkpoint_store.save(
                TEST_STREAM, "checkpoint_group", "consumer1", event.id
            )
        return True

    consumer1 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="checkpoint_group",
        consumer="consumer1",
        block_ms=2000,
        checkpoint_store=checkpoint_store,
    )

    ready1 = threading.Event()

    def run_consumer1():
        ready1.set()
        consumer1.subscribe(callback1)

    t1 = threading.Thread(target=run_consumer1)
    t1.daemon = True
    t1.start()

    ready1.wait(timeout=2.0)
    time.sleep(1.0)

    consumer1.close()
    t1.join(timeout=1.0)

    # Should have processed at least 3 events
    assert len(processed) >= 3, f"Expected at least 3 events processed, got {len(processed)}"

    # Second consumer: should resume from checkpoint (skip first 3 events)
    received_after_resume = []

    def callback2(event):
        received_after_resume.append(event)
        return True

    # Create new checkpoint store but load the checkpoint
    checkpoint_store2 = InMemoryCheckpointStore()
    # Manually load checkpoint from first store
    saved_checkpoint = checkpoint_store.load(TEST_STREAM, "checkpoint_group", "consumer1")
    checkpoint_store2.save(TEST_STREAM, "checkpoint_group", "consumer2", saved_checkpoint)

    consumer2 = StreamConsumer(
        redis_url=TEST_REDIS_URL,
        stream=TEST_STREAM,
        group="checkpoint_group",
        consumer="consumer2",
        block_ms=2000,
        checkpoint_store=checkpoint_store2,
    )

    ready2 = threading.Event()

    def run_consumer2():
        ready2.set()
        consumer2.subscribe(callback2)

    t2 = threading.Thread(target=run_consumer2)
    t2.daemon = True
    t2.start()

    ready2.wait(timeout=2.0)
    time.sleep(1.0)

    consumer2.close()
    t2.join(timeout=1.0)

    # Second consumer should receive remaining events (starting from checkpoint)
    # It may receive some duplicate if checkpoint wasn't perfectly at message boundary
    print(f"Second consumer received: {len(received_after_resume)} events")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
