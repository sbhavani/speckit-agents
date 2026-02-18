# Implementation Plan: Redis Streams Checkpoint Persistence

**Branch**: `006-checkpoint-persistence` | **Date**: 2026-02-17 | **Spec**: [link](./spec.md)
**Input**: Feature specification from `/specs/006-checkpoint-persistence/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Checkpoint persistence for Redis Streams consumers - enabling reliable resume after restarts by persisting consumer position after each acknowledgment and loading saved checkpoint on startup. Integrates existing `CheckpointStore` with `StreamConsumer`, adds validation, monotonic advancement, and error handling for production reliability.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: redis>=5.0, pytest (existing)
**Storage**: Redis (checkpoints stored as string keys)
**Testing**: pytest (existing), mypy, ruff
**Target Platform**: Linux server / Python runtime
**Project Type**: Library (redis_streams module)
**Performance Goals**: Resume within 5 seconds (SC-001), 99.9% checkpoint persistence (SC-003)
**Constraints**: <10s recovery time (SC-004), exactly-once semantics target
**Scale/Scope**: Single consumer instance, small checkpoint data (<1KB per consumer)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status |
|------|--------|
| Constitution file exists but is empty template - proceeding with default principles | ✅ PASS |
| Single project type (library module) - no complexity concerns | ✅ PASS |

**Note**: Constitution file `.specify/memory/constitution.md` exists but contains only template placeholders. Using default software engineering principles.

## Project Structure

### Documentation (this feature)

```text
specs/006-checkpoint-persistence/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/
├── redis_streams/
│   ├── __init__.py
│   ├── checkpoint.py       # EXISTING - CheckpointStore (needs integration)
│   ├── consumer.py         # EXISTING - StreamConsumer (needs checkpoint integration)
│   ├── connection.py      # EXISTING
│   ├── exceptions.py      # EXISTING
│   ├── models.py          # EXISTING
│   ├── monitoring.py      # EXISTING
│   └── producer.py        # EXISTING

tests/
├── unit/
│   └── test_models.py     # EXISTING
└── integration/
    ├── test_concurrent_consumers.py
    ├── test_event_delivery.py
    ├── test_event_ordering.py
    └── test_failure_recovery.py

worker.py                 # Worker implementation (may need updates)
worker_pool.py           # Worker pool
orchestrator.py          # Main orchestrator
```

**Structure Decision**: Single library project - existing `src/redis_streams/` module. Checkpoint integration will add methods to existing `checkpoint.py` and `consumer.py`, plus new tests.

## Phase 0: Research Findings

### Gap Analysis

| Requirement | Current State | Gap |
|-------------|---------------|-----|
| FR-001: Persist checkpoint after ack | `StreamConsumer.acknowledge()` doesn't call `CheckpointStore.save()` | Integration needed |
| FR-002: Load checkpoint on startup | `StreamConsumer` doesn't load checkpoint | New method needed |
| FR-003: Resume from checkpoint | Consumer always reads from `>` (new messages only) | Integration + xreadgroup with checkpoint ID |
| FR-004: Monotonic advancement | `CheckpointStore` uses basic SET | No validation |
| FR-005: Handle storage failures | No error handling/retry in CheckpointStore | Needs implementation |
| FR-006: Validate checkpoint | No validation logic | Needs implementation |

### Key Integration Points

1. **StreamConsumer initialization**: Accept optional `checkpoint_store` parameter
2. **subscribe() method**: Load checkpoint before starting, use checkpoint ID in xreadgroup
3. **acknowledge() method**: Call checkpoint store save after successful xack
4. **Error handling**: Wrap checkpoint operations in try/except with retry logic

## Phase 1: Design Decisions

### Data Flow

```
[Event arrives] → xreadgroup → [Process callback] → [xack] → [CheckpointStore.save()]
                                                                    ↑
[startup] → CheckpointStore.load() ──────────────────────────────────┘
```

### API Changes

**CheckpointStore additions:**
- `save()` - Add monotonic validation (only save if > current)
- `load()` - Add validation of loaded checkpoint (validate format)
- New methods for error handling/retry logic

**StreamConsumer additions:**
- `checkpoint_store` parameter in `__init__()`
- `load_checkpoint()` method
- Modify `subscribe()` to use checkpoint position
- Modify `acknowledge()` to save checkpoint

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | Single library project, minimal complexity | N/A |

