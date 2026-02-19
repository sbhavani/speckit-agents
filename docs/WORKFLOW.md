# Workflow

End-to-end example and phase details.

## Two Modes: Standalone vs Worker Pool

The system can run in two modes:

### Standalone Mode (Single Process)
Orchestrator handles all phases sequentially:
```
PM_SUGGEST → REVIEW → DEV_SPECIFY → DEV_PLAN → DEV_TASKS → PLAN_REVIEW → DEV_IMPLEMENT → CREATE_PR → PM_LEARN
```

### Worker Pool Mode (Distributed)
Orchestrator coordinates, workers implement in parallel:

**Orchestrator:**
```
PM_SUGGEST → REVIEW → (publish to Redis stream) → loop back to PM_SUGGEST
```

**Worker (picks up from stream):**
```
DEV_SPECIFY → DEV_PLAN → DEV_TASKS → PLAN_REVIEW → DEV_IMPLEMENT → CREATE_PR → PM_LEARN
```

## End-to-End Example (Worker Pool Mode)

```
1. Human runs:
   - uv run python orchestrator.py --loop --project agent-team  (coordinator)
   - uv run python worker.py --consumer worker-1              (worker)
   - uv run python worker.py --consumer worker-2              (worker)

2. Orchestrator posts to #product-dev:
   "[PM Agent] Starting feature prioritization..."

3. PM Agent reads docs/PRD.md, scans git log
4. PM Agent returns: "Suggested feature: X (Priority: P1)"

5. Orchestrator posts to #product-dev:
   "[PM Agent] Feature Suggestion:
   **Add X**
   Priority: P1
   Rationale: ..."

6. Human replies: "approve" (or timeout -> auto-approve)

7. Orchestrator publishes feature to Redis stream "feature-requests"
8. Orchestrator posts: "✅ Feature published to work queue. Workers will handle implementation."
9. Orchestrator loops back to PM_SUGGEST for next feature

10. Worker picks up feature from stream:
    - Runs /speckit.specify, /speckit.plan, /speckit.tasks
    - Runs /speckit.implement
      - Hits ambiguity: Asks question
      - Worker posts question to Mattermost

11. PM Agent answers from PRD context
12. Human can override PM answer

13. Worker continues implementation

14. Worker creates PR:
    gh pr create --title "Add X" --body "..."

15. Worker posts to #product-dev:
    "[Dev Agent] PR created: https://github.com/..."

16. Meanwhile, orchestrator has already suggested/implemented next features in parallel!
```

## Phase Details

### PM_SUGGEST
PM Agent reads PRD, analyzes codebase, suggests highest-priority unimplemented feature.

**Output:** Feature name, description, rationale, priority

### REVIEW
Human approves or rejects the feature suggestion.

**Human input:** "approve", "reject", or alternative description
**Timeout:** 300s (configurable) → auto-approve

### DEV_SPECIFY
Dev Agent runs `/speckit.specify` to create SPEC.md.

**Output:** spec.md with user stories, acceptance criteria

### DEV_PLAN
Dev Agent runs `/speckit.plan` to create plan.md.

**Output:** plan.md with technical approach, file structure

### DEV_TASKS
Dev Agent runs `/speckit.tasks` to create tasks.md.

**Output:** tasks.md with task list, dependencies
**Format:** `- [ ] T001 [P] [US1] Description` (use `[P]` for parallelizable)

### PLAN_REVIEW
Human reviews plan before implementation.

**Human input:** "approve", "reject"
**Timeout:** 60s (configurable) → auto-proceed

### DEV_IMPLEMENT
Dev Agent runs `/speckit.implement`.

If tasks.md has `[P]` markers:
- Sequential tasks run first
- Parallel tasks run concurrently in batches

**Dev can ask questions:**
```
{"type": "question", "question": "...", "context": "...", "options": ["A", "B"]}
```

### CREATE_PR
Dev Agent creates branch, commits, opens PR.

### PM_LEARN
PM Agent writes learnings to `.agent/product-manager.md`.

## Question Handling

During implementation, Dev Agent can ask structured questions:

1. Dev outputs JSON with question
2. Orchestrator posts to Mattermost
3. PM Agent answers based on PRD
4. Human can override within 60s
5. Answer fed back to Dev session

## CLI Commands

### Orchestrator (Coordinator)
```bash
# Normal workflow
uv run python orchestrator.py

# Dry run (print to stdout)
uv run python orchestrator.py --dry-run

# Skip PM, implement specific feature
uv run python orchestrator.py --feature "Add X"

# Simple mode (skip specify/plan/tasks)
uv run python orchestrator.py --feature "Add X" --simple

# Resume from last state
uv run python orchestrator.py --resume

# Loop for multiple features
uv run python orchestrator.py --loop

# Validate setup
uv run python orchestrator.py --doctor

# With project (for multi-project configs)
uv run python orchestrator.py --loop --project agent-team
```

### Workers (Implementation)
```bash
# Start a worker (consumes from Redis stream)
uv run python worker.py --consumer worker-1

# Start multiple workers for parallel execution
uv run python worker.py --consumer worker-2
uv run python worker.py --consumer worker-3

# Dry run mode (just logs, doesn't run orchestrator)
uv run python worker.py --consumer worker-1 --dry-run
```
