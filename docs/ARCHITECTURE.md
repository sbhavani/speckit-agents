# Architecture

System components, technical decisions, and dependencies.

## High-Level Architecture

```
+-------------------+     Mattermost API     +-------------------+
|   Mattermost      | <---------------------> |   Orchestrator    |
|   Channel         |                        |   (Python)         |
|   - Human         |                        +----------+----------+
|   - PM Bot        |                                 |
|   - Dev Bot       |                                 v
+-------------------+                         +----------+----------+
                                                  |
                                                  v
                                         +--------+--------+
                                         | Claude Code  |
                                         | CLI (claude) |
                                         +--------+----+
                                                  |
                                                  v
                                         +--------+--------+
                                         | Target Repo   |
                                         | (git worktree)|
                                         +---------------+
```

## Components

### 1. Orchestrator (`orchestrator.py`)

Central script managing workflow state machine.

**State machine phases:**
| Phase | Description | Agent | Checkpoint? |
|-------|-------------|-------|--------------|
| INIT | Load config, verify connectivity | -- | No |
| PM_SUGGEST | PM reads PRD, suggests feature | PM | No |
| REVIEW | Human approves/rejects | -- | **Yes** |
| DEV_SPECIFY | Dev runs `/speckit.specify` | Dev | No |
| DEV_PLAN | Dev runs `/speckit.plan` | Dev | No |
| DEV_TASKS | Dev runs `/speckit.tasks` | Dev | No |
| PLAN_REVIEW | Human reviews plan | PM | **Yes** |
| DEV_IMPLEMENT | Dev runs `/speckit.implement` | Dev+PM | On questions |
| CREATE_PR | Dev creates PR | Dev | No |
| PM_LEARN | PM writes learnings | PM | No |
| DONE | Post PR URL | -- | No |

### 2. Mattermost Bridge (`mattermost_bridge.py`)

Handles Mattermost communication:
- `send(message, sender)` - Post to channel
- `read_posts(limit, after)` - Fetch posts
- `read_new_human_messages()` - Filter human messages
- `wait_for_response(timeout)` - Poll for response

Two bot identities:
- **Dev bot**: For dev agent and orchestrator messages
- **PM bot**: For PM agent messages

### 3. Responder (`responder.py`)

Daemon that listens for commands:
- `/suggest` - Start workflow
- `/suggest "Feature"` - Implement specific feature
- `@product-manager <question>` - Ask PM questions

### 4. Worker (`worker.py`)

Redis Streams consumer for parallel execution.

### 5. Agent Definitions

- `.claude/agents/pm-agent.md` - PM role
- `.claude/agents/dev-agent.md` - Dev role

## Technical Decisions

### Why `claude -p` (headless CLI)?
- Simpler setup (no npm/pip packages)
- Session management built in (`--resume`)
- Output formats (json, stream-json) handle structured communication

### Why Mattermost API directly?
- No extra dependencies
- Full control over API features
- Two bot identities for clear attribution

### Why one orchestrator?
- Coordinated state machine ensures correct ordering
- Human checkpoints centrally managed
- Session IDs shared between agents

### Why Spec Kit?
- Structured output (spec.md, plan.md, tasks.md)
- Phases map cleanly to orchestrator states
- Task checklist format enables progress reporting

## Dependencies

- **uv**: Dependency management
- **Redis**: Cache and session state
- **Claude Code CLI**: AI agent execution
- **GitHub CLI**: PR creation
- **Python 3.10+**: Runtime
- **Mattermost**: Communication channel
