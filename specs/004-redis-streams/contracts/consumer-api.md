# Consumer API Contract

## StreamConsumer

### `subscribe(callback, event_types?)`

Starts consuming messages from the stream. Blocking call.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| callback | callable | Yes | Function to call with each message. Signature: `(message: EventMessage) -> bool`. Return True to acknowledge, False to keep pending |
| event_types | list | No | Filter to specific event types |

**Returns:** None (blocks until closed)

**Message Object:**
```python
class EventMessage:
    id: str           # Redis message ID
    stream: str       # Stream name
    event_type: str   # From message body
    payload: dict     # Deserialized JSON
    metadata: dict    # Optional metadata
    timestamp: str   # ISO 8601
```

**Errors:**
- `GroupNotFoundError` - Consumer group doesn't exist
- `RedisConnectionError`

---

### `acknowledge(message_id)`

Acknowledges a processed message.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| message_id | string | Yes | ID of message to acknowledge |

**Returns:** `int` - Number of messages acknowledged

**Errors:**
- `RedisConnectionError`

---

### `get_pending()`

Gets list of pending (unacknowledged) messages for this consumer.

**Parameters:** None

**Returns:** `list[PendingMessage]` where:
```python
class PendingMessage:
    id: str       # Message ID
    consumer: str # Consumer that received it
    idle_ms: int  # Time since last delivery
    delivered: int # Delivery count
```

**Errors:**
- `RedisConnectionError`

---

### `close()`

Gracefully stops consuming and closes connection.

**Parameters:** None

**Returns:** None

---

## ConsumerGroupManager

### `create_group(stream, group, start_id?)`

Creates a consumer group. Idempotent - succeeds if group exists.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| stream | string | Yes | Stream name |
| group | string | Yes | Group name |
| start_id | string | No | Where to start reading: "0" (all), "$" (new only), or specific ID |

**Returns:** `bool` - True if created, False if already existed

**Errors:**
- `StreamNotFoundError` - Stream doesn't exist and mkstream=False
- `RedisConnectionError`

---

### `delete_group(stream, group)`

Deletes a consumer group and all its pending messages.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| stream | string | Yes | Stream name |
| group | string | Yes | Group name |

**Returns:** `bool` - True if deleted

**Errors:**
- `RedisConnectionError`

---

### `list_groups(stream)`

Lists all consumer groups for a stream.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| stream | string | Yes | Stream name |

**Returns:** `list[string]` - Group names

**Errors:**
- `StreamNotFoundError`
- `RedisConnectionError`

---

### `get_group_info(stream, group)`

Gets consumer group statistics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| stream | string | Yes | Stream name |
| group | string | Yes | Group name |

**Returns:** `dict`:
```python
{
    "name": str,
    "consumers": int,
    "pending": int,
    "last_delivered_id": str
}
```

**Errors:**
- `GroupNotFoundError`
- `RedisConnectionError`

---

## Error Handling Contract

| Error Type | Description | Recovery |
|------------|-------------|----------|
| `RedisConnectionError` | Cannot connect to Redis | Retry with backoff |
| `GroupNotFoundError` | Consumer group doesn't exist | Create group first |
| `StreamNotFoundError` | Stream doesn't exist | Create stream first |
| `ConsumerCrashedError` | No heartbeat from consumer | Run reclaim process |
| `PayloadTooLargeError` | Event exceeds 1MB | Validate before publish |

---

## Backpressure Handling

When consumer cannot keep up:

1. **XINFO** command reports stream length and lag
2. Consumer can report `lag` metric to monitoring
3. Producer should monitor and slow down if lag > threshold
4. Consider adding more consumers to consumer group
