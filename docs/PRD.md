# PRD: Agent Team

A multi-agent orchestration system where a **Product Manager agent** and a **Developer agent** collaborate to ship features autonomously, communicating through Mattermost. Human operator can intervene at any time.

## User Stories

### P0: Core Workflow (Must Have)

**As a** operator,
**I want** the system to automatically suggest, implement, and PR features from the PRD,
**So that** features ship without manual intervention.

- [P0-US1] PM Agent reads PRD and suggests highest-priority unimplemented feature
- [P0-US2] Human approves/rejects feature suggestion in Mattermost
- [P0-US3] Dev Agent runs `/speckit.specify` to create SPEC.md
- [P0-US4] Dev Agent runs `/speckit.plan` to create plan.md
- [P0-US5] Dev Agent runs `/speckit.tasks` to create tasks.md
- [P0-US6] Human reviews plan before implementation (60s yolo window)
- [P0-US7] Dev Agent runs `/speckit.implement` to implement all tasks
- [P0-US8] Dev Agent creates PR via `gh pr create`
- [P0-US9] PM Agent records learnings to `.agent/product-manager.md`

**Acceptance Criteria:**
- Each workflow produces a PR URL posted to Mattermost
- Human can approve/reject at REVIEW and PLAN_REVIEW checkpoints
- All phases logged to Mattermost with summaries

### P1: Human Intervention (Must Have)

**As a** human team member,
**I want** to ask questions and get answers during implementation,
**So that** I can guide the feature direction.

- [P1-US1] Human can @mention PM Agent with questions during implementation
- [P1-US2] PM Agent answers based on PRD context
- [P1-US3] Dev Agent can ask structured questions (JSON format)
- [P1-US4] Questions posted to Mattermost, PM answers, human can override

**Acceptance Criteria:**
- Questions routed correctly (product → PM, implementation → Dev)
- Human override takes precedence over PM answer

### P2: Parallel Execution (Should Have)

**As a** operator,
**I want** multiple features to implement in parallel,
**So that** throughput increases.

- [P2-US1] Worker pool spawns N parallel workers
- [P2-US2] Each worker runs independent orchestrator
- [P2-US3] Redis Streams distributes work to available workers

**Acceptance Criteria:**
- Multiple workers can run simultaneously without conflicts
- Each worker maintains independent state

### P3: Resilience (Could Have)

**As a** operator,
**I want** the system to recover from failures,
**So that** interrupted workflows can resume.

- [P3-US1] State persisted to Redis or file
- [P3-US2] `--resume` flag picks up from last phase
- [P3-US3] Timeouts handled gracefully with retry logic

**Acceptance Criteria:**
- Workflow resumes at correct phase with preserved context

### P4: Observability (Could Have)

**As a** operator,
**I want** visibility into workflow progress and metrics,
**So that** I can monitor system health.

- [P4-US1] Phase durations tracked and displayed in summary
- [P4-US2] Tool augmentation logs pre/post phase state
- [P4-US3] JSONL logs for post-mortem analysis

**Acceptance Criteria:**
- Summary shows time per phase
- Logs available for debugging

## Non-Functional Requirements

### Performance
- Phase timeouts: SPECIFY=60min, PLAN=60min, TASKS=60min, IMPLEMENT=60min
- Mattermost poll interval: 15s (configurable)
- Worker pool scales to N concurrent workers

### Security
- Bot tokens stored in config.yaml (not in code)
- Local config overrides via `config.local.yaml` (gitignored)
- Mattermost API calls only to configured URL

### Reliability
- Claude session preserved via `--resume`
- Exponential backoff on transient failures (5s, 20s, 80s)
- Worktree cleanup mandatory after PR creation

## Test Scenarios

1. **Happy path**: Run orchestrator, approve feature, verify PR created
2. **Rejection**: Run orchestrator, reject at REVIEW, verify no PR
3. **Question**: During impl, ask @product-manager question, verify answer
4. **Resume**: Kill mid-implementation, resume with --resume, verify continuation
5. **Parallel**: Start 3 workers, queue 3 features, verify all complete
