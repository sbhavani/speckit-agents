# Data Model: Checkpoint Persistence

## Entities

### Checkpoint

A marker indicating the last successfully processed event position for a consumer.

| Field | Type | Description |
|-------|------|-------------|
| `stream` | str | Stream name |
| `group` | str | Consumer group name |
| `consumer` | str | Consumer name (unique within group) |
| `message_id` | str | Last processed message ID (e.g., "1234567890-0") |
| `created_at` | datetime | When checkpoint was created (optional) |

**Key**: `redis_streams:checkpoint:{stream}:{group}:{consumer}`

**Validation Rules**:
- `message_id` must match Redis message ID format: `^\d+-\d+$`
- Must be greater than any previously stored checkpoint (monotonic)

### Consumer (existing, extended)

| Field | Type | Description |
|-------|------|-------------|
| `checkpoint_store` | CheckpointStore | Optional checkpoint persistence |
| `checkpoint` | str | Current checkpoint position (in-memory cache) |

---

## State Transitions

### Consumer Lifecycle

```
[STARTUP]
    ↓
[LOAD CHECKPOINT] → CheckpointStore.load()
    ↓
[SUBSCRIBE with checkpoint position]
    ↓
[PROCESS MESSAGE]
    ↓
[ACKNOWLEDGE] → xack + CheckpointStore.save()
    ↓
[REPEAT until stopped]
```

### Checkpoint States

```
[None] → [Saved after first ack] → [Updated on each subsequent ack]
         ↓
      [Invalid] → [Fallback to None]
```

---

## API Contracts

### CheckpointStore

```python
class CheckpointStore:
    """Stores consumer checkpoint positions in Redis."""

    def save(
        self,
        stream: str,
        group: str,
        consumer: str,
        message_id: str,
        monotonic: bool = True,
    ) -> bool:
        """Save checkpoint for a consumer.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name
            message_id: Message ID to save
            monotonic: Only save if greater than existing (default True)

        Returns:
            True if saved, False if skipped (monotonic check failed)
        """

    def load(
        self,
        stream: str,
        group: str,
        consumer: str,
    ) -> Optional[str]:
        """Load checkpoint for a consumer.

        Returns:
            Message ID or None if no checkpoint exists
        """

    def validate(self, message_id: str) -> bool:
        """Validate checkpoint format.

        Returns:
            True if valid Redis message ID format
        """
```

### StreamConsumer (additions)

```python
class StreamConsumer:
    def __init__(
        self,
        # ... existing params
        checkpoint_store: Optional[CheckpointStore] = None,
        auto_checkpoint: bool = True,
    ):
        """Initialize with optional checkpoint support.

        Args:
            checkpoint_store: Store for checkpoint persistence
            auto_checkpoint: Auto-save checkpoint after ack (default True)
        """

    def load_checkpoint(self) -> Optional[str]:
        """Load checkpoint from store.

        Returns:
            Last checkpoint message ID or None
        """

    def acknowledge(self, message_id: str) -> int:
        """Acknowledge message and save checkpoint.

        Returns:
            Number of messages acknowledged
        """
```

---

## Data Flow

```
┌─────────────────┐
│   Event         │
│   (Redis)       │
└────────┬────────┘
         │ xreadgroup
         ▼
┌─────────────────┐
│ StreamConsumer  │
│   subscribe()   │
└────────┬────────┘
         │
    ┌────┴────┐
    │ callback│
    └────┬────┘
         │ ack + checkpoint
         ▼
┌─────────────────┐
│  xack +         │
│  checkpoint.save│
└─────────────────┘
```

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| No checkpoint exists | Start from beginning (use ">") |
| Checkpoint beyond stream | Use checkpoint anyway, Redis returns empty |
| Checkpoint storage fails | Retry 3x, log error, continue processing |
| Invalid checkpoint format | Treat as no checkpoint |
| Rapid restart before flush | In-memory cache + eventual consistency |
