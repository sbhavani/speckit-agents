# Quickstart: Checkpoint Persistence

## Installation

No new dependencies required. Already includes `redis>=5.0`.

```bash
uv sync
```

## Basic Usage

### 1. Create a checkpoint store

```python
from redis_streams.checkpoint import CheckpointStore

# Redis-backed store
checkpoint_store = CheckpointStore(redis_url="redis://localhost:6379")

# Or in-memory store (for testing)
from redis_streams.checkpoint import InMemoryCheckpointStore
checkpoint_store = InMemoryCheckpointStore()
```

### 2. Create consumer with checkpoint support

```python
from redis_streams.consumer import StreamConsumer
from redis_streams.checkpoint import CheckpointStore

checkpoint_store = CheckpointStore()

consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="events",
    group="my-group",
    consumer="consumer-1",
    checkpoint_store=checkpoint_store,  # New parameter
    auto_checkpoint=True,                 # Auto-save after ack
)
```

### 3. Process events (checkpoint auto-saved)

```python
def process_event(event):
    print(f"Processing: {event.id}")
    return True  # Return True to acknowledge

# Checkpoint is automatically saved after each acknowledgment
consumer.subscribe(process_event)
```

### 4. Resume from checkpoint on restart

```python
# On restart, consumer automatically loads last checkpoint
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="events",
    group="my-group",
    consumer="consumer-1",
    checkpoint_store=checkpoint_store,
    auto_checkpoint=True,
)

# This will resume from the last saved checkpoint
consumer.subscribe(process_event)
```

### 5. Manual checkpoint control

```python
# Load checkpoint explicitly
checkpoint = consumer.load_checkpoint()
print(f"Resuming from: {checkpoint}")

# Checkpoint validation
from redis_streams.checkpoint import CheckpointStore

store = CheckpointStore()
if store.validate("1234567890-0"):
    print("Valid checkpoint format")
else:
    print("Invalid checkpoint")
```

## Running Tests

```bash
# Unit tests
uv run pytest tests/unit/ -v

# Integration tests (requires Redis)
uv run pytest tests/integration/ -v -m integration
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `checkpoint_store` | CheckpointStore | None | Store for persistence |
| `auto_checkpoint` | bool | True | Auto-save after ack |
| `checkpoint.monotonic` | bool | True | Only advance forward |

## Error Handling

Checkpoint failures are logged but don't stop event processing:

```python
import logging

logging.getLogger("redis_streams.checkpoint").setLevel(logging.WARNING)
```
