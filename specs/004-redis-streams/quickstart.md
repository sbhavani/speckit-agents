# Quickstart: Redis Streams Event-Driven Architecture

## Prerequisites

- Redis 5.0+ running
- Python 3.10+
- `redis` package: `pip install redis`

---

## Producer Example

```python
from redis_streams import StreamProducer, StreamManager

# Initialize manager and create stream
manager = StreamManager("redis://localhost:6379")
manager.create_stream("data-updates", max_length=10000)

# Create producer
producer = StreamProducer(
    redis_url="redis://localhost:6379",
    stream_name="data-updates",
    max_length=10000
)

# Publish events
message_id = producer.publish(
    event_type="price.update",
    payload={"symbol": "AAPL", "price": 150.25},
    metadata={"source": "market-feed"}
)
print(f"Published message: {message_id}")

producer.close()
```

---

## Consumer Example

```python
from redis_streams import StreamConsumer, ConsumerGroupManager

# Create consumer group (run once)
group_mgr = ConsumerGroupManager("redis://localhost:6379")
group_mgr.create_group("data-updates", "processors", start_id="0")

# Create consumer
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="data-updates",
    group="processors",
    consumer="worker-1"
)

# Process messages
def handle_message(msg):
    print(f"Received: {msg.event_type} - {msg.payload}")
    return True  # Auto-acknowledge

try:
    consumer.subscribe(handle_message, event_types=["price.update"])
except KeyboardInterrupt:
    consumer.close()
    print("Consumer stopped")
```

---

## Configuration

### Minimal Config (YAML)

```yaml
redis_streams:
  url: "redis://localhost:6379"

  producer:
    stream: "events"
    max_length: 10000

  consumer:
    group: "my-group"
    block_ms: 5000
    count: 10
```

### Environment Variables

```bash
export REDIS_URL="redis://localhost:6379"
export STREAM_NAME="events"
export CONSUMER_GROUP="processors"
export CONSUMER_NAME="worker-1"
```

---

## Testing Locally

### Start Redis (Docker)

```bash
docker run -d -p 6379:6379 redis:7
```

### Run Tests

```bash
pytest tests/unit/test_streams.py -v
```

---

## Advanced Features

### Checkpoint Resume (Auto-Recovery)

Consumers automatically persist checkpoints to Redis after acknowledging messages and resume from the last checkpoint on restart:

```python
# Use Redis-backed checkpoint (default)
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="data-updates",
    group="processors",
    consumer="worker-1",
    use_redis_checkpoint=True  # Default
)

# Or use in-memory checkpoint (for testing)
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="data-updates",
    group="processors",
    consumer="worker-1",
    use_redis_checkpoint=False
)
```

### Reclaim Loop (Failure Recovery)

Enable automatic stale message reclaim to handle consumers that crash without acknowledging:

```python
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="data-updates",
    group="processors",
    consumer="worker-1",
    reclaim_enabled=True,
    reclaim_interval_ms=30000,  # Check every 30 seconds
    reclaim_min_idle_ms=30000    # Claim messages idle > 30 seconds
)
```

### Connection Retry with Exponential Backoff

Connection errors automatically retry with exponential backoff (configured in RedisConnection):

```python
from redis_streams import RedisConnection

# Custom retry settings
conn = RedisConnection(
    url="redis://localhost:6379",
    max_retries=5,
    retry_base_delay=0.1,  # Start at 100ms
    retry_max_delay=30.0    # Max 30 seconds
)
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| `BUSYGROUP` error | Group already exists; use `mkstream=True` or handle gracefully |
| Messages never delivered | Check consumer group exists before consuming |
| Stream grows unbounded | Always set `max_length` on producer |
| Consumer crashes, messages lost | Enable `reclaim_enabled=True` for automatic recovery |
| Consumer restarts, processes old messages | Checkpoints auto-resume from last acknowledged message |

---

## Next Steps

1. Run the example code above
2. Review [data-model.md](data-model.md) for entity definitions
3. See [contracts/consumer-api.md](contracts/consumer-api.md) for full API
4. Generate tasks with `/speckit.tasks`
