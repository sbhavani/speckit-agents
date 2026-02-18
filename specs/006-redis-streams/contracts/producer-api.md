# Producer API Contract

## StreamProducer

### `publish(event_type, payload, metadata?) => message_id`

Publishes an event to the stream.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| event_type | string | Yes | Classification for routing (e.g., "data.update") |
| payload | dict | Yes | Event data to serialize as JSON |
| metadata | dict | No | Optional key-value pairs for routing/filtering |

**Returns:** `string` - Redis-generated message ID (format: timestamp-sequence)

**Errors:**
- `StreamNotFoundError` - Stream doesn't exist and auto-create disabled
- `PayloadTooLargeError` - Event exceeds 1MB
- `RedisConnectionError` - Connection to Redis failed

**Validation:**
- `event_type` must be non-empty string
- `payload` must serialize to under 1MB

---

### `close()`

Closes the Redis connection.

**Parameters:** None

**Returns:** None

---

## StreamManager

### `create_stream(name, retention_ms?, max_length?)`

Creates a new stream with optional retention settings.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| name | string | Yes | Stream identifier |
| retention_ms | int | No | Auto-delete after ms (default: 86400000 = 24h) |
| max_length | int | No | Max messages before trimming |

**Returns:** `bool` - True if created, False if already exists

**Errors:**
- `RedisConnectionError`

---

### `delete_stream(name)`

Deletes a stream and all its messages.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| name | string | Yes | Stream identifier |

**Returns:** `int` - Number of keys deleted

**Errors:**
- `RedisConnectionError`

---

### `get_stream_info(name)`

Gets stream metadata and statistics.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| name | string | Yes | Stream identifier |

**Returns:** `dict` with keys:
- `length`: int - Number of messages
- `first_entry`: dict - First message
- `last_entry`: dict - Last message
- `radix_tree_keys`: int - Internal storage info
- `groups`: int - Number of consumer groups

**Errors:**
- `StreamNotFoundError`
- `RedisConnectionError`

---

## Configuration

```yaml
redis_streams:
  producer:
    redis_url: "redis://localhost:6379"
    stream_name: "events"
    max_length: 10000
    auto_create_stream: true

  consumer:
    redis_url: "redis://localhost:6379"
    streams:
      - name: "events"
        group: "my-group"
        consumer: "consumer-1"
    block_ms: 5000
    count: 10
    auto_ack: false
```
