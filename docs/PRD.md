# PRD: Agent Team — PM + Developer Code Agents

## Overview

A multi-agent orchestration system where a **Product Manager agent** and a **Developer agent** collaborate to ship features autonomously, communicating through Mattermost via OpenClaw. A human operator can observe and intervene at any time through the same Mattermost channel.

Both agents are powered by Claude Code CLI (`claude -p`) running in headless mode. The Developer agent uses **speckit** for structured feature specification and implementation.

## Goals

1. **Autonomous feature delivery**: PM reads PRD, picks a feature, Dev implements it, PR is created
2. **Transparent communication**: All decisions and questions are visible in Mattermost
3. **Human-in-the-loop**: Operator can approve, reject, redirect, or answer questions at any point
4. **Structured implementation**: Dev follows speckit workflow (specify → plan → tasks → implement)
5. **Minimal infrastructure**: Uses existing tools (Claude Code CLI, OpenClaw, Mattermost)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 Mattermost Channel                       │
│                                                          │
│  🧑 Human        📋 PM Agent        💻 Dev Agent        │
│  (intervene       (suggest &         (spec, build,       │
│   anytime)         answer Qs)         create PR)         │
└──────────────────────┬───────────────────────────────────┘
                       │
          OpenClaw Gateway (mac-mini-i7.local)
          ws://127.0.0.1:18789 (loopback)
          accessed via: ssh sb@mac-mini-i7.local
                       │
┌──────────────────────┴───────────────────────────────────┐
│               orchestrator.py (local)                     │
│                                                           │
│   State Machine:                                          │
│   INIT → PM_SUGGEST → REVIEW → DEV_SPECIFY → DEV_PLAN   │
│        → DEV_TASKS → DEV_IMPLEMENT → CREATE_PR → DONE    │
│                                                           │
│   ┌─────────────┐                  ┌──────────────┐      │
│   │  PM Agent   │   questions →    │  Dev Agent    │      │
│   │ (claude -p) │   ← answers     │ (claude -p)   │      │
│   │             │                  │               │      │
│   │ • Read PRD  │                  │ • speckit.*   │      │
│   │ • Prioritize│                  │ • Implement   │      │
│   │ • Answer Qs │                  │ • Create PR   │      │
│   └─────────────┘                  └──────────────┘      │
└───────────────────────────────────────────────────────────┘
```

## Components

### 1. Orchestrator (`orchestrator.py`)

The central script that manages the workflow state machine.

**Responsibilities:**
- Drives the workflow through phases
- Spawns Claude Code headless sessions for each agent
- Bridges agent output to Mattermost via OpenClaw CLI (over SSH)
- Handles human intervention (approval, rejection, redirection)
- Manages agent session continuity (resume via session_id)

**State machine phases:**

| Phase | Description | Agent | Human checkpoint? |
|-------|-------------|-------|-------------------|
| `INIT` | Load config, verify connectivity | — | No |
| `PM_SUGGEST` | PM reads PRD, suggests highest-priority unimplemented feature | PM | No |
| `REVIEW` | Post suggestion to Mattermost, wait for approval | — | **Yes** (approve/reject/redirect) |
| `DEV_SPECIFY` | Dev runs `/speckit.specify` with the approved feature | Dev | No |
| `DEV_PLAN` | Dev runs `/speckit.plan` | Dev | No |
| `DEV_TASKS` | Dev runs `/speckit.tasks` | Dev | No |
| `DEV_IMPLEMENT` | Dev runs `/speckit.implement`, may ask questions | Dev | On questions |
| `CREATE_PR` | Dev creates branch, commits, opens PR via `gh pr create` | Dev | No |
| `DONE` | Post PR link to Mattermost | — | No |

**Question handling during implementation:**
1. Dev agent is instructed to output questions as structured JSON
2. Orchestrator detects question markers in output
3. Question is posted to Mattermost (as Dev Agent)
4. PM Agent is asked to answer based on PRD context
5. PM answer is posted to Mattermost
6. Orchestrator waits briefly for human override
7. Final answer is fed back to Dev Agent session (via `--resume`)

### 2. Mattermost Bridge (`mattermost_bridge.py`)

Handles all communication with Mattermost through OpenClaw CLI over SSH.

**Key operations:**
- `send(message, sender)` — Post to Mattermost channel via `openclaw message send`
- `read_since(after_id)` — Read new messages via `openclaw message read`
- `wait_for_response(timeout)` — Poll for human responses

**OpenClaw CLI commands used:**
```bash
# Send a message to Mattermost channel
ssh sb@mac-mini-i7.local "openclaw message send \
  --channel mattermost \
  --target '<channel_id>' \
  -m 'message text'"

# Read recent messages
ssh sb@mac-mini-i7.local "openclaw message read \
  --channel mattermost \
  --target '<channel_id>' \
  --limit 10 \
  --json"

# Send as specific bot account (PM vs Dev)
ssh sb@mac-mini-i7.local "openclaw message send \
  --channel mattermost \
  --account productManager \
  --target '<channel_id>' \
  -m 'PM says: ...'"
```

**Configuration from OpenClaw (discovered):**
- Mattermost base: `http://mac-mini-i7.tail58a751.ts.net:8065`
- Bot account: `productManager` (name: `product-manager`)
- Gateway: `ws://127.0.0.1:18789` (loopback, accessed via SSH)
- Chat mode: `oncall` (responds when @mentioned)
- DM/Group policy: `open`

### 3. PM Agent (`.claude/agents/pm-agent.md`)

A Claude Code subagent definition for the Product Manager role.

**System prompt focus:**
- Read and understand docs/PRD.md
- Analyze what features are already implemented (via git log, codebase scanning)
- Prioritize unimplemented features by business value, dependencies, and risk
- Provide clear feature descriptions suitable for speckit.specify
- Answer developer questions about requirements with PRD context

**Tools:** Read, Glob, Grep, Bash(git log), Bash(git diff)

### 4. Dev Agent (`.claude/agents/dev-agent.md`)

A Claude Code subagent definition for the Developer role.

**System prompt focus:**
- Execute the speckit workflow for a given feature
- Follow the project's coding conventions (from CLAUDE.md)
- Ask structured questions when requirements are ambiguous
- Create clean PRs with descriptive titles and bodies

**Tools:** Read, Write, Edit, Bash, Glob, Grep

### 5. Configuration (`config.yaml`)

```yaml
project:
  name: finance-agent
  path: /Users/sbhavani/code/finance-agent
  prd_path: docs/PRD.md

openclaw:
  ssh_host: sb@mac-mini-i7.local
  mattermost_channel: "product-dev"
  mattermost_account: productManager

workflow:
  approval_timeout: 300        # seconds to wait for human before auto-proceeding
  question_timeout: 120        # seconds to wait for human answer to dev questions
  auto_approve: false          # if true, skip human approval for feature suggestion
```

## Workflow: End-to-End Example

```
1. Human runs: python orchestrator.py
2. Orchestrator posts to #product-dev:
   "[PM Agent] Starting feature prioritization..."

3. PM Agent reads docs/PRD.md, scans git log and codebase
4. PM Agent returns: "Suggested feature: Add parallel benchmark evaluation
   Rationale: Currently evaluation runs sequentially; PRD lists this as P1"

5. Orchestrator posts to #product-dev:
   "[PM Agent] 📋 Feature Suggestion:
   **Add parallel benchmark evaluation**
   Priority: P1
   Rationale: Sequential evaluation is slow; PRD requires parallel support.
   Reply 'approve', 'reject', or suggest an alternative."

6. Human replies: "approve" (or timeout → auto-approve)

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
    "[Dev Agent] ✅ PR created: https://github.com/sbhavani/finance-agent/pull/42"

15. Orchestrator exits (or loops for next feature)
```

## Implementation Plan

### Phase 1: Core Infrastructure
- [ ] Create project structure (`agent-team/`)
- [ ] Write `config.yaml` with defaults
- [ ] Write `mattermost_bridge.py` (OpenClaw SSH wrapper)
- [ ] Test sending/reading messages to Mattermost

### Phase 2: Agent Definitions
- [ ] Write `.claude/agents/pm-agent.md`
- [ ] Write `.claude/agents/dev-agent.md`
- [ ] Test agents independently with `claude -p`

### Phase 3: Orchestrator
- [ ] Implement state machine in `orchestrator.py`
- [ ] Wire up PM Agent → Mattermost → approval flow
- [ ] Wire up Dev Agent → speckit workflow → question handling
- [ ] Wire up PR creation → Mattermost notification
- [ ] Add `--dry-run` mode for testing without Mattermost

### Phase 4: Polish
- [ ] Add logging (file + Mattermost)
- [ ] Add `--resume` to pick up from a failed state
- [ ] Add `--loop` mode to continuously process features
- [ ] Add second OpenClaw bot account for Dev Agent identity

## Technical Decisions

### Why `claude -p` (headless CLI) over Agent SDK?

- Simpler setup: no npm/pip package to manage, just the CLI
- Session management built in (`--resume SESSION_ID`)
- Output formats (json, stream-json) handle structured communication
- The orchestrator is lightweight Python; heavy lifting is in Claude Code
- Can upgrade to Agent SDK later if needed (same underlying engine)

### Why SSH to OpenClaw instead of WebSocket gateway?

- Gateway is loopback-only (`bind=loopback` in config)
- SSH is already configured and working (`ssh sb@mac-mini-i7.local`)
- `openclaw message send/read` CLI is simpler than raw WebSocket protocol
- No need to manage WebSocket connection lifecycle
- Can switch to direct WebSocket if gateway is rebound to LAN/Tailscale

### Why one orchestrator instead of two independent agents?

- Coordinated state machine ensures correct ordering
- Human-in-the-loop checkpoints are centrally managed
- Session IDs can be shared (PM answers questions in Dev's context)
- Easier to add features like `--resume` and `--loop`
- Simpler debugging: one log, one process

### Why speckit for the Dev workflow?

- Already in use across multiple projects (finance-agent, github-issue-triage-hub, live-set-revival)
- Structured output (spec.md, plan.md, tasks.md) makes progress trackable
- Phases map cleanly to orchestrator states
- Task checklist format enables progress reporting to Mattermost

## Dependencies

- **Claude Code CLI** (`claude`): Must be installed and authenticated
- **OpenClaw** (`openclaw`): Running on mac-mini-i7.local with Mattermost plugin
- **GitHub CLI** (`gh`): For PR creation
- **Python 3.10+**: For the orchestrator
- **SSH access**: To `sb@mac-mini-i7.local`
- **speckit commands**: Must be installed in the target project's `.claude/commands/`

## Configuration Reference

### Environment Variables
- `ANTHROPIC_API_KEY`: For Claude Code (if not using other auth)
- `AGENT_TEAM_CONFIG`: Path to config.yaml (default: `./config.yaml`)

### OpenClaw Mattermost Setup (already done)
- Mattermost server: `http://mac-mini-i7.tail58a751.ts.net:8065`
- Bot account: `productManager`
- Plugin: `@openclaw/mattermost` (loaded)
- Gateway: port 18789, loopback bind

## Future Enhancements

- **Multiple Dev Agents**: Fan out parallel speckit phases to separate sessions
- **Code Review Agent**: Third agent that reviews Dev's PR before posting
- **Mattermost slash commands**: Trigger workflows from Mattermost (`/suggest-feature`)
- **Persistent state**: SQLite or file-based state for crash recovery
- **Metrics dashboard**: Track features shipped, time-to-PR, questions asked
- **Second bot account**: Separate Mattermost identity for Dev Agent
