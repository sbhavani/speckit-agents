# Implementation Plan: Add Phase Duration to Summary

**Branch**: `005-phase-duration-summary` | **Date**: 2026-02-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-phase-duration-summary/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Track and display elapsed time for each workflow phase in the Mattermost summary output. The core functionality exists in `orchestrator.py` (phase timing tracking via `_phase_timings`, duration formatting via `_fmt_duration`, and summary table generation). Gaps identified: phase timings not persisted across workflow resume, no handling for missing/incomplete timing data, no support for hour/day durations.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: Redis (optional), PyYAML, Python standard library (time, datetime, json)
**Storage**: File-based JSON state (`.agent-team-state.json`) + optional Redis
**Testing**: pytest
**Target Platform**: Linux server (runs via SSH to mac-mini)
**Project Type**: CLI orchestration tool
**Performance Goals**: Phase durations displayed within 1 second of summary generation (SC-002)
**Constraints**: Must handle workflow resume, incomplete timing data gracefully
**Scale**: Single workflow at a time, 10 phases max

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Constitution**: The constitution.md is a template with no filled principles - no gates to evaluate.

**Result**: PASS (no gates to evaluate)

## Project Structure

### Documentation (this feature)

```text
specs/005-phase-duration-summary/
├── plan.md              # This file
├── spec.md               # Feature specification
└── tasks.md             # /speckit.tasks output (to be generated)
```

### Source Code (repository root)

```text
orchestrator.py          # Contains: _phase_timings, _fmt_duration, _post_summary
tests/
└── test_orchestrator.py # Contains tests for _fmt_duration and _phase_timings
```

**Structure Decision**: Single Python project - feature added to existing `orchestrator.py`

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | Feature already exists in codebase | N/A |

## Research Findings

### Feature Already Implemented

The phase duration tracking feature already exists in `orchestrator.py`:

1. **Phase timing tracking** (lines 518, 708-739):
   - `_phase_timings: list[tuple[str, float]]` stores (phase_name, duration_seconds)
   - Each phase timing is recorded after the method executes

2. **Duration formatting** (lines 1486-1492):
   - `_fmt_duration(seconds)` converts to human-readable format
   - Handles: <60s ("Xs"), 60-3599s ("Xm Ys"), >=3600s ("Xh Ym")

3. **Summary generation** (lines 1494-1536):
   - Builds markdown table with phase names and durations
   - Includes total workflow duration

4. **Tests** (tests/test_orchestrator.py:228-243, 272-290):
   - Unit tests for `_fmt_duration` function
   - Tests for `_phase_timings` being populated

### Identified Gaps

| Gap | FR Reference | Description |
|-----|--------------|-------------|
| 1. No state persistence | FR-006 | `_phase_timings` not saved in `_save_state()` - lost on resume |
| 2. No missing data handling | FR-006 | No graceful handling when timing data is missing |
| 3. No hour/day support | FR-005 | `_fmt_duration` doesn't format hours/days explicitly |

### Required Fixes

1. **Persist phase timings**: Add `_phase_timings` to `_save_state()` data dict
2. **Restore timings on resume**: Load saved timings after resume detection
3. **Handle missing data**: Check for None/incomplete timings before formatting
4. **Enhance duration format**: Add explicit hour/day handling for very long phases

---

## Phase 0: Research

**Status**: COMPLETE - No research needed

The feature already exists in `orchestrator.py`. No unknown technical decisions require research. The identified gaps are implementation fixes rather than design decisions.

## Phase 1: Design

**Status**: COMPLETE - No design work needed

- **Data model**: Uses existing `WorkflowState` dataclass + `_phase_timings` list
- **No API contracts**: Internal feature, no external interfaces
- **No quickstart needed**: No new user-facing functionality

## Next Steps

Proceed to `/speckit.tasks` to generate tasks for the identified fixes:
1. Persist `_phase_timings` in state
2. Restore timings on resume
3. Add missing timing data handling in `_post_summary`
4. Enhance `_fmt_duration` for hour/day support
