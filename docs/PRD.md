# PRD: Spec Kit Agent Team — PM + Developer Code Agents

## Overview

A multi-agent orchestration system where a **Product Manager agent** and a **Developer agent** collaborate to ship features autonomously, communicating through Mattermost. A human operator can observe and intervene at any time through the same Mattermost channel.

Both agents are powered by Claude Code CLI (`claude -p`) running in headless mode. The Developer agent uses **Spec Kit** for structured feature specification and implementation.

## Goals

1. **Autonomous feature delivery**: PM reads PRD, picks a feature, Dev implements it, PR is created
2. **Transparent communication**: All decisions and questions are visible in Mattermost
3. **Human-in-the-loop**: Operator can approve, reject, redirect, or answer questions at any point
4. **Structured implementation**: Dev follows Spec Kit workflow (specify -> plan -> tasks -> implement)
5. **Minimal infrastructure**: Uses existing tools (Claude Code CLI, Mattermost, Redis)

## Architecture

```
+---------------------------------------------------------+
|                 Mattermost Channel                       |
|                                                          |
|  Human           PM Agent           Dev Agent            |
|  (intervene       (answer Qs)         (spec, build,      |
|   anytime)                               create PR)      |
+------------------------+---------------------------------+
                         |
            Mattermost API (http://localhost:8065)
                         |
+------------------------+---------------------------------+
|              Local Services (uv)                         |
|                                                         |
|  +-------------+     +--------------+    +-----------+  |
|  |  Responder  | --> | Orchestrator| -->|  Claude   |  |
|  | (listens)   |     | (workflow)  |    |  CLI      |  |
|  +-------------+     +--------------+    +-----------+  |
|         |                                      |       |
|         v                                      v       |
|  +-------------+                       +--------------+ |
|  |   Redis    |                       | Target Repo  | |
|  |  (docker)  |                       | (worktree)   | |
|  +-------------+                       +--------------+ |
+---------------------------------------------------------+

State Machine (Orchestrator):
INIT -> PM_SUGGEST -> REVIEW -> DEV_SPECIFY -> DEV_PLAN
-> DEV_TASKS -> PLAN_REVIEW -> DEV_IMPLEMENT -> CREATE_PR -> PM_LEARN -> DONE
```

## Components

### 1. Responder (`responder.py`)

A lightweight daemon that listens for commands and @mentions in Mattermost.

**Responsibilities:**
- Polls for new messages in all channels
- Detects `/suggest` command to start workflows
- Handles @product-manager mentions (PRD + context)
- Spawns orchestrator workflows on demand
- Answers questions using channel context

**Commands:**
- `/suggest` — Start feature suggestion workflow
- `/suggest "Feature name"` — Start implementation of specific feature
- `@product-manager <question>` — Ask PM questions (PRD + channel context)
- `@dev-agent <question>` — *[coming soon]* Ask Dev questions with channel context

### 2. Orchestrator (`orchestrator.py`)

The central script that manages the workflow state machine.

**Responsibilities:**
- Drives the workflow through phases
- Spawns Claude Code headless sessions for each agent
- Bridges agent output to Mattermost via REST API
- Handles human intervention (approval, rejection, redirection)
- Manages agent session continuity (resume via session_id)
- Creates git worktrees for isolated development (doesn't pollute original repo)

**State machine phases:**

| Phase | Description | Agent | Human checkpoint? |
|-------|-------------|-------|-------------------|
| `INIT` | Load config, verify connectivity | -- | No |
| `PM_SUGGEST` | PM reads PRD, suggests highest-priority unimplemented feature | PM | No |
| `REVIEW` | Post suggestion to Mattermost, wait for approval | -- | **Yes** (approve/reject/redirect) |
| `DEV_SPECIFY` | Dev runs `/speckit.specify`, posts summary to channel | Dev | No |
| `DEV_PLAN` | Dev runs `/speckit.plan`, posts summary to channel | Dev | No |
| `DEV_TASKS` | Dev runs `/speckit.tasks`, posts task list to channel | Dev | No |
| `PLAN_REVIEW` | 60s window to ask PM questions or reject before impl | PM | **Yes** (yolo auto-proceed) |
| `DEV_IMPLEMENT` | Dev implements, orchestrator polls for human questions | Dev+PM | On questions |
| `CREATE_PR` | Dev creates branch, commits, opens PR via `gh pr create` | Dev | No |
| `PM_LEARN` | PM writes learnings to `.agent/product-manager.md` journal | PM | No |
| `DONE` | Post PR link to Mattermost | -- | No |

**Question handling during implementation:**
1. Dev agent is instructed to output questions as structured JSON
2. Orchestrator detects question markers in output
3. Question is posted to Mattermost (as Dev Agent)
4. PM Agent is asked to answer based on PRD context
5. PM answer is posted to Mattermost
6. Orchestrator waits briefly for human override
7. Final answer is fed back to Dev Agent session (via `--resume`)

### 3. Mattermost Bridge (`mattermost_bridge.py`)

Handles all communication with Mattermost via REST API:
- **Send**: Via Mattermost REST API (`/api/v4/posts`)
- **Read**: Via Mattermost REST API (`/api/v4/channels/<id>/posts`)

**Key operations:**
- `send(message, sender)` -- Post to channel via Mattermost API
- `read_posts(limit, after)` -- Fetch posts via Mattermost REST API
- `read_new_human_messages()` -- Filter for non-bot, non-system messages since last check
- `wait_for_response(timeout)` -- Poll for human responses

Uses two bot identities:
- **Dev bot**: For dev agent and orchestrator messages
- **PM bot**: For PM agent messages

### 4. PM Agent (`.claude/agents/pm-agent.md`)

A Claude Code subagent definition for the Product Manager role.

**System prompt focus:**
- Read and understand the target project's PRD
- Analyze what features are already implemented (via git log, codebase scanning)
- Prioritize unimplemented features by business value, dependencies, and risk
- Provide clear feature descriptions suitable for speckit.specify
- Answer developer questions about requirements with PRD context

**Tools:** Read, Glob, Grep, Bash(git log), Bash(git diff)

### 5. Dev Agent (`.claude/agents/dev-agent.md`)

A Claude Code subagent definition for the Developer role.

**System prompt focus:**
- Execute the speckit workflow for a given feature
- Follow the project's coding conventions (from CLAUDE.md)
- Ask structured questions when requirements are ambiguous
- Create clean PRs with descriptive titles and bodies

**Tools:** Read, Write, Edit, Bash, Glob, Grep

### 6. Configuration (`config.yaml`)

All environment-specific values live in config.yaml. Override locally with `config.local.yaml` (gitignored).

```yaml
# Multi-project mode
projects:
  finance-agent:
    path: /Users/sb/code/finance-agent
    prd_path: docs/PRD.md
    channel_id: bhpbt6h6tnt3nrnq8yi6n9k7br
  live-set-revival:
    path: /Users/sb/code/live-set-revival
    prd_path: docs/SPEC.md
    channel_id: bxkopjqjntntd89978uhb8wg7y

openclaw:
  ssh_host: localhost  # Unused, kept for backward compatibility
  anthropic_api_key: sk-cp-...  # Minimax API key for responder PM questions
  anthropic_base_url: https://api.minimax.io/anthropic
  anthropic_model: MiniMax-M2.1

mattermost:
  channel_id: bhpbt6h4xtnem8int5ccmbo4dw
  url: "http://localhost:8065"
  dev_bot_token: <dev bot token>
  dev_bot_user_id: <dev bot user id>
  pm_bot_token: <product-manager bot token>
  pm_bot_user_id: <product-manager bot user id>

workflow:
  approval_timeout: 300
  question_timeout: 120
  plan_review_timeout: 60
  auto_approve: false
  loop: false
  impl_poll_interval: 15
  user_mention: ""
```

### API Configuration

The responder uses the Minimax API (Anthropic-compatible) for answering PM questions:

```yaml
openclaw:
  anthropic_api_key: sk-cp-...  # Minimax API key
  anthropic_base_url: https://api.minimax.io/anthropic
  anthropic_model: MiniMax-M2.1
```

This allows fast responses to @product-manager questions without spawning a full Claude session.

### Redis Caching

Redis is used for caching to improve performance:

| Key Pattern | Value | TTL |
|-------------|-------|-----|
| `prd:{project_path}:{prd_path}` | PRD file content | 1 hour |
| `session:{session_id}` | Orchestrator session state | 24 hours |
| `channel:{channel_id}:project` | Project config for channel | 1 hour |

**Caching strategy:**
- **PRD content**: Cached after first read, expires after 1 hour. Invalidated when config changes.
- **Session state**: Persists across orchestrator restarts for resume functionality.
- **Channel-project mapping**: Caches which project belongs to which channel for faster lookups.

## Workflow: End-to-End Example

```
1. Human runs: uv run python orchestrator.py
2. Orchestrator posts to #product-dev:
   "[PM Agent] Starting feature prioritization..."

3. PM Agent reads docs/PRD.md, scans git log and codebase
4. PM Agent returns: "Suggested feature: Add parallel benchmark evaluation
   Rationale: Currently evaluation runs sequentially; PRD lists this as P1"

5. Orchestrator posts to #product-dev:
   "[PM Agent] Feature Suggestion:
   **Add parallel benchmark evaluation**
   Priority: P1
   Rationale: Sequential evaluation is slow; PRD requires parallel support.
   Reply 'approve', 'reject', or suggest an alternative."

6. Human replies: "approve" (or timeout -> auto-approve)

7. Orchestrator posts: "[Dev Agent] Starting speckit workflow..."
8. Dev Agent runs /speckit.specify, /speckit.plan, /speckit.tasks
   Progress posted to Mattermost after each step

9. Dev Agent runs /speckit.implement
   - Hits ambiguity: "Should parallel evaluation share a single output file
     or create per-worker files?"
   - Orchestrator detects question, posts to Mattermost

10. PM Agent answers from PRD context:
    "Single output file with thread-safe writes, per the data transparency principle"

11. Human sees PM answer, can override: "Actually, per-worker files merged at the end"

12. Dev Agent receives answer, continues implementation

13. Dev Agent creates PR:
    gh pr create --title "Add parallel benchmark evaluation" --body "..."

14. Orchestrator posts to #product-dev:
    "[Dev Agent] PR created: https://github.com/sbhavani/finance-agent/pull/42"

15. Orchestrator exits (or loops for next feature)
```

## Implementation Plan

### Phase 1: Core Infrastructure [DONE]
- [x] Create project structure (`agent-team/`)
- [x] Write `config.yaml` with all env-specific values
- [x] Write `mattermost_bridge.py` (hybrid: OpenClaw send + Mattermost API read)
- [x] Test sending/reading messages to Mattermost (verified live)
- [x] Fix SSH banner filtering, zsh URL quoting
- [x] Switch to uv for dependency management
- [x] 17 unit tests + 3 integration tests, all passing

### Phase 2: Agent Definitions [DONE]
- [x] Write `.claude/agents/pm-agent.md`
- [x] Write `.claude/agents/dev-agent.md`
- [x] Test agents independently with `claude -p`

### Phase 3: Orchestrator [DONE]
- [x] Implement state machine in `orchestrator.py`
- [x] Wire up PM Agent -> Mattermost -> approval flow
- [x] Wire up Dev Agent -> speckit workflow -> question handling
- [x] Wire up PR creation -> Mattermost notification
- [x] Add `--dry-run` mode for testing without Mattermost
- [x] End-to-end dry-run test (--verbose flag feature, full pipeline)
- [x] End-to-end live test with Mattermost (PR #2: --dry-run flag, PR #3: --version flag)
- [x] `--feature` flag to skip PM and directly implement a named feature
- [x] Graceful timeout handling (captures partial output, preserves session)

### Phase 4: Dual Bot Identity & Bidirectional Communication [DONE]
- [x] Separate PM bot identity (product-manager bot via Mattermost API)
- [x] Dev/Orchestrator messages via OpenClaw CLI (openclaw bot)
- [x] Bidirectional PM Q&A during implementation (background thread polling)
- [x] Human can ask PM questions during any review phase
- [x] Both bot user IDs filtered when reading human messages

### Phase 5: Plan Review & UX [DONE]
- [x] Phase summaries posted to Mattermost after specify, plan, and tasks
- [x] PLAN_REVIEW checkpoint before implementation starts
- [x] 60-second yolo mode (auto-proceed if no objection, configurable)
- [x] Emoji approval support (thumbs up/down)
- [x] @mention stripping (e.g. `@openclaw go` recognized as `go`)
- [x] 30-minute timeouts for long-running features

### Phase 6: Hardening
- [x] Add `--resume` to pick up from a failed state (persist WorkflowState to disk)
- [x] Add structured logging (file + Mattermost summary)
- [x] Handle `claude -p` timeout/crash gracefully (retry with backoff)
- [x] Handle SSH connection failures (retry, alert to Mattermost)
- [x] Validate config on startup (check SSH connectivity, channel exists, bot token works)
- [ ] Rate limiting / cost tracking for Claude API calls (won't do)

### Phase 7: Polish
- [x] Progress reporting during long speckit phases (stream-json parsing)
- [x] Mattermost thread support (keep each feature's discussion in a thread)
- [x] Config-driven target project switching (work on different repos)
- [ ] Post-PR code review agent (review before merging)
- [ ] Metrics: time-per-phase, total cost, features shipped

## Technical Decisions

### Why `claude -p` (headless CLI) over Agent SDK?

- Simpler setup: no npm/pip package to manage, just the CLI
- Session management built in (`--resume SESSION_ID`)
- Output formats (json, stream-json) handle structured communication
- The orchestrator is lightweight Python; heavy lifting is in Claude Code
- Can upgrade to Agent SDK later if needed (same underlying engine)

### Why Mattermost API directly?

- **Simplicity**: No extra dependencies (OpenClaw, SSH)
- **Full control**: Direct access to all API features (threading, reactions, etc.)
- **Two bot identities**: Dev bot and PM bot for clear message attribution
- **Runs locally**: Connects directly to Mattermost at http://localhost:8065

### Why one orchestrator instead of two independent agents?

- Coordinated state machine ensures correct ordering
- Human-in-the-loop checkpoints are centrally managed
- Session IDs can be shared (PM answers questions in Dev's context)
- Easier to add features like `--resume` and `--loop`
- Simpler debugging: one log, one process

### Why Spec Kit for the Dev workflow?

- Already in use across multiple projects (finance-agent, github-issue-triage-hub, live-set-revival)
- Structured output (spec.md, plan.md, tasks.md) makes progress trackable
- Phases map cleanly to orchestrator states
- Task checklist format enables progress reporting to Mattermost

## Dependencies

- **uv**: Dependency management
- **Redis**: Cache and session state (via docker)
- **Claude Code CLI** (`claude`): Must be installed and authenticated locally
- **GitHub CLI** (`gh`): For PR creation
- **Python 3.10+**: For the orchestrator
- **Mattermost**: Running at http://localhost:8065
- **speckit commands**: Must be installed in the target project's `.claude/commands/`

## Configuration Reference

### Environment Variables
- `ANTHROPIC_API_KEY`: For Claude Code (if not using other auth)
- `AGENT_TEAM_CONFIG`: Path to config.yaml (default: `./config.yaml`)
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379`)
- `HOST_WORKDIR`: Host working directory for docker path mapping

### Mattermost Setup

- Mattermost server: `http://localhost:8065`
- Dev bot: `openclaw` (ID: `prmnsceu8bg8tm1kmb3zzhbdwr`, is_bot: true)
- PM bot: `product-manager` (ID: `osnrc8yrpffifj56friubo5dxr`, is_bot: true)
- Channel: `#product-dev` (ID: `bhpbt6h4xtnem8int5ccmbo4dw`)

## Future Enhancements

### MoSCoW Roadmap

#### Must Have (Critical)
- **Error recovery**: `--resume` already works, but improve handling of corrupted state files
- **Timeout handling**: Better Claude timeout management (already has retries, could be more robust)

#### Should Have (Important)
- **Slash commands + Webhooks**: Trigger workflows from Mattermost (`/agent start --project live-set-revival`) via slash command that hits a webhook. Eliminates polling.
- **Persistent state**: SQLite or file-based state for crash recovery (currently uses JSON files)
- **Metrics dashboard**: Track features shipped, time-to-PR, questions asked

#### Could Have (Nice to Have)
- **Multiple Dev Agents**: Fan out parallel Spec Kit phases to separate sessions
- **Code Review Agent**: Third agent that reviews Dev's PR before posting
- **Redis Streams**: Replace polling with event-driven architecture for lower latency
- **Hatchet integration**: Background task queue for non-blocking orchestrator

#### Won't Have (Not for now)
- **Temporal**: Enterprise workflow orchestration - overkill for current needs
- **Full multi-agent parallelism**: Complex to implement, limited benefit currently

### Performance & Background Tasks

Current architecture runs synchronously - orchestrator blocks waiting for Claude. For production-scale usage, consider:

#### Priority 1: Redis Streams (Low Effort)
Replace polling with Redis Streams for event-driven architecture:
- `XADD` workflow events → Redis stream
- `XREAD` blocks until events arrive (no polling)
- Also enables: workflow history, replay, debugging
- **Effort**: Medium (refactor message polling)
- **Benefit**: Lower latency, better observability

#### Priority 2: Hatchet (Medium Effort)
Lightweight background task queue: https://github.com/hatchet-dev/hatchet
- Queue long-running tasks (specify, plan, implement)
- Webhook callbacks when tasks complete
- Built-in retries, timeouts, dashboards
- Go-based, simpler than Temporal
- **Effort**: Medium (add worker, queue tasks)
- **Benefit**: Non-blocking orchestrator, can run multiple workflows

#### Priority 3: Temporal (High Effort)
Full workflow orchestration: https://github.com/temporalio/temporal
- Durable executions (survive restarts)
- Built-in retry logic, timeouts, saga patterns
- Activity scheduling, child workflows
- Web UI for debugging
- **Effort**: High (full rearchitecture)
- **Benefit**: Enterprise-grade reliability, complex workflows

#### Comparison

| Feature | Redis Streams | Hatchet | Temporal |
|---------|--------------|----------|----------|
| Complexity | Low | Medium | High |
| Durability | Basic | Good | Excellent |
| Debug UI | No | Yes | Yes |
| Learning curve | Low | Medium | High |
| When to use | Polling replacement | Background jobs | Complex workflows |

**Recommendation**: Start with **Redis Streams** (lowest effort, immediate improvement). Graduate to **Hatchet** if you need background task queues. Temporal is only worth it for enterprise requirements.

### Potential UX Improvements (ideas)
- **Phase duration**: Show duration per phase in summary (e.g., "Specify: 4m, Plan: 5m, Implement: 15m")
- **Condensed summary**: Instead of individual tool calls, show "15 files changed, 3 new files" after implementation

---

## Learnings from First AI-Generated Feature (Redis Streams)

### What Worked Well
1. **Speed**: 25 minutes from suggestion to PR - faster than human
2. **Scope**: Generated 25 files with producer, consumer, checkpoints, monitoring
3. **Structure**: Good overall architecture with separate modules

### Issues Found (Required Human Fix)
1. **Syntax error in models.py**: Malformed dictionary literal in `Event.to_dict()`
   - `"payload": json.dumps "timestamp": self.timestamp` - missing parentheses
   - **Fix**: Run basic Python syntax check before PR
2. **Redis API compatibility**: Used `xpending_ext` which isn't available in all Redis versions
   - **Fix**: Add mypy type checking + version-compatible API
3. **Test logic**: Some integration tests had incorrect assertions
   - **Fix**: Add unit tests for contract (publish → read roundtrip)

### Improvements Made
1. Added **mypy** for type checking to CI
2. Added **ruff** for linting to CI
3. Added **CI workflow** to run tests/type/lint on PRs

### Takeaways
- AI generates good structure but makes subtle syntax/logic errors
- **Always run tests before human review** - would have caught syntax error
- Type checking (mypy) catches API compatibility issues
- Integration tests need careful assertion logic

