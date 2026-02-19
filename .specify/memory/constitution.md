# Agent Team Constitution

## Core Principles

### I. Product-Driven Development
Every feature MUST originate from a documented product requirement (PRD). Features are prioritized based on user value, business impact, and dependency order. The PM Agent maintains the backlog and suggests features in priority order. No implementation without clear product rationale.

### II. Human-in-the-Loop
Human approval is REQUIRED at key workflow gates: feature suggestion (REVIEW), plan review (PLAN_REVIEW), and final PR. Humans can intervene, ask questions, reject, or approve at any point. The system supports yolo mode only when explicitly requested by human.

### III. Structured Implementation via Spec Kit
All features MUST follow the Spec Kit workflow: specify -> plan -> tasks -> implement. The /speckit commands enforce structured thinking and artifact generation. Simple mode (--simple) MAY be used for quick fixes but standard features require full specification.

### IV. Test-First Approach
For substantive features, tests MUST be written before implementation. Contract and integration tests validate interfaces between components. Unit tests ensure correctness of individual components. Tests document expected behavior.

### V. Isolated Worktree Execution
Every workflow runs in an isolated git worktree in /tmp/. Feature branches are created fresh per workflow. Worktrees share git objects with main repo for efficiency. Cleanup of worktrees and branches is mandatory after PR creation.

### VI. Observable Workflows
All phases MUST log actions and outputs. Tool augmentation captures pre/post phase state. JSONL logs enable post-mortem analysis and research. Workflow state persisted in Redis for resume capability.

### VII. Agent Collaboration
PM Agent and Dev Agent communicate through structured handoffs. PM Agent answers clarifying questions during implementation. Dev Agent creates artifacts (spec.md, plan.md, tasks.md). Both agents log learnings to .agent/ journals.

## Development Workflow

### Phase Gates

1. **PM_SUGGEST**: PM Agent analyzes PRD and suggests highest-priority feature
2. **REVIEW**: Human approves or rejects feature suggestion
3. **DEV_SPECIFY**: Dev Agent creates SPEC.md via /speckit.specify
4. **DEV_PLAN**: Dev Agent creates PLAN.md via /speckit.plan
5. **DEV_TASKS**: Dev Agent creates TASKS.md via /speckit.tasks
6. **PLAN_REVIEW**: Human reviews plan (60s yolo window before auto-proceed)
7. **DEV_IMPLEMENT**: Dev Agent executes tasks via /speckit.implement
8. **CREATE_PR**: Dev Agent opens pull request
9. **PM_LEARN**: PM Agent documents learnings

### Quality Gates

- SPEC.md must include user stories with priorities, acceptance criteria, and success metrics
- PLAN.md must include technical context, project structure, and complexity justification
- TASKS.md must organize by user story for independent implementation and testing
- Implementation must pass existing tests before PR
- PR description must reference spec and plan

## Technical Standards

### Target Projects

- Python 3.10+ projects using uv for dependency management
- Docker for services (Redis, etc.)
- Git for version control
- Claude Code CLI for AI agent execution
- GitHub CLI for PR creation
- Mattermost for human communication

### Artifact Locations

- Feature specs: `.specs/[###-feature-name]/`
- Agent journals: `.agent/pm-agent.md`, `.agent/dev-agent.md`
- Constitution: `.specify/memory/constitution.md`
- Spec templates: `.specify/templates/`

### Configuration

- Project-specific: `config.yaml`
- Local overrides: `config.local.yaml` (gitignored)
- No hardcoded credentials in source

## Governance

### Constitution Updates

- MAJOR version bump: Backward incompatible principle changes
- MINOR version bump: New principles or materially expanded guidance
- PATCH version bump: Clarifications, wording, typo fixes
- All amendments require Sync Impact Report documenting changes

### Compliance

- All PRs should verify alignment with constitution principles
- Complexity must be justified (see PLAN.md Complexity Tracking section)
- Use this constitution for runtime development guidance
- Use CLAUDE.md for project-specific instructions

**Version**: 1.0.0 | **Ratified**: 2026-02-18 | **Last Amended**: 2026-02-18
