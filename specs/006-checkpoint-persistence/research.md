# Research: Redis Streams Checkpoint Persistence

**Feature**: 006-checkpoint-persistence
**Date**: 2026-02-17

## Research Questions

### RQ-001: How to integrate checkpoint with Redis Streams consumer groups?

**Finding**: Redis XREADGROUP reads from either:
- `>` - only new messages not yet delivered to this consumer
- Specific message ID - resume from that position

The consumer should save the last processed message ID and use that as the start position on next subscription.

**Decision**: Use the message ID (e.g., "1234567890-0") as checkpoint. On startup, load checkpoint and pass to xreadgroup with that ID instead of `>`.

**Rationale**: This enables true resume from last position. Redis handles the semantics correctly - messages with ID > checkpoint will be delivered.

---

### RQ-002: How to ensure monotonic checkpoint advancement?

**Finding**: Redis Streams message IDs are timestamp-sequence format (ms-ordinal). We can compare them lexicographically as strings since they follow `timestamp-sequence` format.

**Decision**: Before saving checkpoint, compare new ID with existing checkpoint. Only save if new ID > existing checkpoint (lexicographically).

**Alternatives considered**:
- Store both timestamp and sequence separately - more complex
- Always overwrite - loses the guarantee but simpler

---

### RQ-003: How to handle checkpoint storage failures gracefully?

**Finding**: Need retry logic with backoff. Redis operations can fail transiently (connection issues, timeout).

**Decision**: Implement retry decorator/wrapper with:
- Max 3 retries
- Exponential backoff (0.1s, 0.2s, 0.4s)
- Log failures but don't crash consumer

**Rationale**: Checkpoint failure shouldn't stop event processing. If ack succeeds but checkpoint fails, consumer can reprocess on restart (safe but less efficient).

---

### RQ-004: How to validate checkpoint data?

**Finding**: Checkpoint should be validated for:
- Format: matching Redis message ID pattern (`\d+-\d+`)
- Reasonableness: not beyond current stream length (optional)

**Decision**: Add `validate_checkpoint()` method that:
- Checks format with regex
- Optionally verifies against stream info
- Returns None/invalid if validation fails

---

### RQ-005: What happens if checkpoint is beyond stream length?

**Finding**: This can happen if stream was trimmed/compacted. Redis XREADGROUP with ID beyond stream returns no messages (behaves like `>`).

**Decision**: Don't validate against stream length at load time. Let Redis handle it - consumer will just wait for new messages.

---

## Summary

| Question | Decision |
|----------|----------|
| Integration point | Use checkpoint ID in xreadgroup stream position |
| Monotonic advancement | Compare IDs lexicographically before save |
| Error handling | Retry with exponential backoff, max 3 attempts |
| Validation | Regex format check only |
| Out-of-bounds | Let Redis handle naturally |

## References

- Redis XREADGROUP: https://redis.io/commands/xreadgroup
- Redis Streams: https://redis.io/docs/data-types/streams/
- Message IDs: Timestamp-sequence format for ordering
