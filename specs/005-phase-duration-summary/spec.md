# Feature Specification: Add Phase Duration to Summary

**Feature Branch**: `005-phase-duration-summary`
**Created**: 2026-02-17
**Status**: Draft
**Input**: User description: "Add phase duration to summary"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Phase Durations in Summary (Priority: P1)

A human operator reviewing the workflow summary in Mattermost can see how long each phase took to complete.

**Why this priority**: This is the core value of the feature - giving operators insight into workflow timing without needing to analyze logs.

**Independent Test**: Can be tested by running a workflow and verifying the summary message includes duration information for each phase.

**Acceptance Scenarios**:

1. **Given** a workflow has completed all phases, **When** the summary is displayed, **Then** each phase shows its duration in a human-readable format
2. **Given** a workflow is in progress, **When** the current phase is displayed, **Then** the elapsed time for the current phase is shown

---

### User Story 2 - Compare Phase Durations Across Runs (Priority: P2)

A human operator can compare how long similar workflows took in the past by reviewing historical summaries.

**Why this priority**: Enables operators to identify performance trends and bottlenecks across multiple workflow executions.

**Independent Test**: Can be tested by running multiple workflows and verifying each summary contains consistent, comparable duration data.

**Acceptance Scenarios**:

1. **Given** multiple workflow runs have completed, **When** reviewing their summaries, **Then** each phase duration is formatted consistently for easy comparison

---

### User Story 3 - Identify Slow Phases (Priority: P3)

A human operator can quickly identify which phase took the longest in a workflow execution.

**Why this priority**: Helps operators pinpoint optimization opportunities in the workflow.

**Independent Test**: Can be tested by running a workflow and verifying the longest phase can be identified from the summary.

**Acceptance Scenarios**:

1. **Given** a workflow summary with multiple phase durations, **When** viewing the summary, **Then** durations are displayed in chronological order with clear labels

---

### Edge Cases

- What happens when a phase duration cannot be measured (e.g., system clock issues)?
- How are very short durations displayed (under 1 second)?
- How are long durations displayed (hours or days)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST record the start time when each workflow phase begins
- **FR-002**: System MUST record the end time when each workflow phase completes
- **FR-003**: System MUST calculate the duration between phase start and end times
- **FR-004**: System MUST include phase durations in the summary output
- **FR-005**: Duration MUST be displayed in a human-readable format (e.g., "2m 30s", "1h 15m")
- **FR-006**: System MUST handle cases where phase timing data is incomplete or missing

### Key Entities

- **Phase**: A discrete stage in the workflow (PM suggest, Review, Specify, Plan, Tasks, Implement, PR)
- **Phase Duration**: The elapsed time from phase start to phase completion
- **Summary**: The output message posted to Mattermost containing workflow information

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can see the duration of each completed phase in the summary message
- **SC-002**: Phase durations are displayed within 1 second of summary generation
- **SC-003**: 100% of completed phases show their duration in the summary
- **SC-004**: Duration format is consistent across all phases and readable by non-technical users
