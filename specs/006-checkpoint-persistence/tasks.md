# Tasks: Redis Streams Checkpoint Persistence

**Feature**: 006-checkpoint-persistence
**Generated**: 2026-02-17
**Source**: plan.md, spec.md, data-model.md, contracts/

## Overview

| Metric | Value |
|--------|-------|
| Total Tasks | 10 |
| User Stories | 3 (P1: 2, P2: 1) |
| MVP Scope | User Story 1 only |

## Implementation Strategy

**MVP First**: User Story 1 delivers core checkpoint persistence. User Stories 2-3 build on that foundation incrementally.

**Parallel Opportunities**: Tasks T002-T003 can run in parallel (different files). Tasks T004-T005 can run in parallel.

---

## Phase 1: Setup

*No setup required - existing project structure already initialized.*

---

## Phase 2: Foundational

*Review existing code to understand current implementation.*

- [ ] T001 Review existing CheckpointStore and StreamConsumer implementations in src/redis_streams/

**Goal**: Understand current API and identify exact integration points.

---

## Phase 3: User Story 1 - Persistent Checkpoint After Processing

**Priority**: P1
**Goal**: Consumer saves checkpoint after each successful acknowledgment
**Independent Test**: Process events, stop consumer, verify checkpoint position is saved

### Implementation Tasks

- [ ] T002 [P] [US1] Add monotonic validation to CheckpointStore.save() in src/redis_streams/checkpoint.py

- [ ] T003 [P] [US1] Add checkpoint_store parameter and auto_checkpoint to StreamConsumer.__init__() in src/redis_streams/consumer.py

- [ ] T004 [US1] Modify StreamConsumer.acknowledge() to save checkpoint after xack in src/redis_streams/consumer.py

**Test Criteria**: After processing and acknowledging an event, the checkpoint position is persisted.

---

## Phase 4: User Story 2 - Resume From Checkpoint on Startup

**Priority**: P1
**Goal**: Consumer loads checkpoint on startup and resumes from saved position
**Independent Test**: Process events, kill consumer, restart, verify it continues from saved position

### Implementation Tasks

- [ ] T005 [P] [US2] Add StreamConsumer.load_checkpoint() method in src/redis_streams/consumer.py

- [ ] T006 [US2] Modify StreamConsumer.subscribe() to use checkpoint position in xreadgroup call in src/redis_streams/consumer.py

**Test Criteria**: After restart, consumer resumes from the last saved checkpoint without re-processing events.

---

## Phase 5: User Story 3 - Checkpoint Storage Reliability

**Priority**: P2
**Goal**: Checkpoint operations handle failures gracefully and validate data
**Independent Test**: Simulate storage failures, verify graceful handling

### Implementation Tasks

- [ ] T007 [P] [US3] Add CheckpointStore.validate() method with regex format check in src/redis_streams/checkpoint.py

- [ ] T008 [US3] Add retry logic with exponential backoff to CheckpointStore operations in src/redis_streams/checkpoint.py

**Test Criteria**: Checkpoint operations retry on transient failures, invalid checkpoints are rejected.

---

## Phase 6: Polish

*Cross-cutting concerns and final integration.*

- [ ] T009 Update exports in src/redis_streams/__init__.py to expose new public API

- [ ] T010 Run tests and verify linting passes: uv run pytest tests/ -v && uv run ruff check src/

---

## Dependencies

```
T001 (Foundational)
    ↓
T002 ─── T003 ──→ T004
    ↓      ↓        ↓
    └───────┴────────┘
              ↓
T005 ──→ T006
    ↓
T007 ──→ T008
    ↓
T009 ──→ T010
```

**Story Completion Order**:
- US1 (T002-T004): Must complete before US2 can fully test
- US2 (T005-T006): Builds on US1
- US3 (T007-T008): Can be tested independently, builds on both US1 and US2

---

## Parallel Execution Examples

**Within User Story 1**:
```bash
# Run in parallel - different files
uv run python -c "
# T002: Modify checkpoint.py
# T003: Modify consumer.py __init__
"
```

**Across Stories**:
```bash
# After T001, T002-T003 can run in parallel
# After US1 complete, US2 and US3 can run in parallel
```

---

## MVP Scope

**Suggested MVP**: User Story 1 only (T002-T004)

This delivers the core value proposition: checkpoint persistence after processing. User Stories 2-3 enhance reliability and resume capability but are not strictly required for initial release.

**MVP Test**: Process events, verify checkpoint saved after acknowledgment.

---

## Task Count Summary

| Phase | Tasks | User Story |
|-------|-------|------------|
| Phase 2: Foundational | 1 | - |
| Phase 3: US1 | 3 | Persistent Checkpoint |
| Phase 4: US2 | 2 | Resume on Startup |
| Phase 5: US3 | 2 | Storage Reliability |
| Phase 6: Polish | 2 | - |
| **Total** | **10** | **3** |
