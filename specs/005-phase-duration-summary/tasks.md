# Tasks: Add Phase Duration to Summary

**Feature**: Add Phase Duration to Summary
**Branch**: 005-phase-duration-summary
**Generated**: 2026-02-17

## Overview

This feature adds phase duration tracking to the workflow summary in Mattermost. The core functionality already exists in `orchestrator.py` — tasks focus on fixing gaps: state persistence, missing data handling, and duration format enhancements.

## Dependencies

```
US1 (View Phase Durations)
  └─ US2 (Compare Across Runs)
       └─ US3 (Identify Slow Phases)
```

US1 is the MVP. US2 and US3 depend on US1's core implementation.

## Implementation Strategy

- **MVP**: US1 - Core duration display in summary
- **Phase 2**: US2 - Consistent formatting (covers edge cases)
- **Phase 3**: US3 - Chronological ordering for identifying slow phases

---

## Phase 1: Foundational (Gap Fixes)

Gap fixes that enable the core feature to work correctly across workflow resumes.

- [ ] T001 Add `_phase_timings` to state persistence in orchestrator.py
  - File: `orchestrator.py`
  - Edit `_save_state()` method to include `"phase_timings": self._phase_timings` in the data dict
  - Location: around line 618-631

- [ ] T002 [P] Handle missing timing data in _post_summary in orchestrator.py
  - File: `orchestrator.py`
  - Edit `_post_summary()` to check for None/incomplete timings before formatting
  - Use default "N/A" for missing durations
  - Location: around line 1507-1514

- [ ] T003 Enhance _fmt_duration for hour/day support in orchestrator.py
  - File: `orchestrator.py`
  - Modify `_fmt_duration()` to explicitly handle >= 3600s (hours) and >= 86400s (days)
  - Format: "1d 2h 30m" for days, "2h 15m 30s" for hours
  - Location: around line 1486-1492

- [ ] T004 Verify existing tests pass
  - File: `tests/test_orchestrator.py`
  - Run: `uv run pytest tests/test_orchestrator.py -v`
  - Ensure existing _fmt_duration tests (lines 228-243) still pass

---

## Phase 2: User Story 1 - View Phase Durations in Summary (P1)

**Goal**: Display phase durations in Mattermost summary

**Independent Test**: Run a workflow and verify summary message includes duration for each phase

- [ ] T005 [US1] Run dry-test workflow to verify durations display
  - File: `orchestrator.py`
  - Run: `uv run python orchestrator.py --dry-run`
  - Verify summary output shows phase durations in table format

---

## Phase 3: User Story 2 - Compare Phase Durations Across Runs (P2)

**Goal**: Ensure consistent duration formatting across multiple workflow runs

**Independent Test**: Run multiple workflows, verify consistent format

- [ ] T006 [US2] [P] Add edge case tests for _fmt_duration in tests/test_orchestrator.py
  - File: `tests/test_orchestrator.py`
  - Add test for 3600s (1 hour) → "1h"
  - Add test for 3661s (1h 1m 1s) → "1h 1m"
  - Add test for 86400s (1 day) → "1d"
  - Add test for 90061s (1d 1h 1m 1s) → "1d 1h 1m"
  - Location: after existing _fmt_duration tests (around line 243)

- [ ] T007 [US2] Verify format consistency across multiple runs
  - Run dry-test twice and compare duration format in outputs

---

## Phase 4: User Story 3 - Identify Slow Phases (P3)

**Goal**: Display durations in chronological order to identify slow phases

**Independent Test**: Verify longest phase can be identified from summary

- [ ] T008 [US3] [P] Verify phase timings display in chronological order
  - File: `orchestrator.py`
  - Verify `_post_summary()` builds table from `_phase_timings` in order
  - Each row appended in sequence: `(phase.name, time.time() - t0)`
  - Location: line 1507-1514

---

## Phase 5: Integration & Polish

- [ ] T009 Run full test suite
  - Run: `uv run pytest tests/test_orchestrator.py -v`
  - All tests must pass

- [ ] T010 Verify resume functionality preserves phase timings
  - Start workflow, interrupt with Ctrl+C
  - Resume with `--resume` flag
  - Verify summary shows complete timings

---

## Summary

| Phase | Task Count | Description |
|-------|------------|-------------|
| Foundational | 4 | Gap fixes for persistence, missing data, duration format |
| US1 | 1 | Core duration display |
| US2 | 2 | Format consistency & tests |
| US3 | 1 | Chronological ordering verification |
| Polish | 2 | Integration tests |
| **Total** | **10** | |

**MVP Scope**: Phase 1 + Phase 2 (T001-T007) — enables core feature with edge case handling

**Parallel Opportunities**:
- T002 and T003 can be done in parallel (different methods)
- T006 and T008 can be done in parallel (tests and verification)

**Independent Test Criteria**:
- US1: Summary shows duration for each phase
- US2: Multiple runs show consistent duration format
- US3: Phases listed in order, longest identifiable
