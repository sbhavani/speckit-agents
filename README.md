# Agent Team

> Autonomous feature delivery using Spec Kit — PM + Dev agents collaborate through Mattermost (self-hosted chat, like Slack)

A multi-agent orchestration system where a **Product Manager agent** and a **Developer agent** collaborate to ship features autonomously through a [Mattermost](https://mattermost.com/) chat server. Human operator can observe and intervene at any time.

Both agents are powered by Claude Code CLI. The Developer agent uses **[Spec Kit](https://github.com/github/spec-kit)** for structured specification and implementation.

## Status

[![CI](https://github.com/sbhavani/speckit-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/sbhavani/speckit-agents/actions)

## Relationship to Spec Kit

**Spec Kit** provides the structured workflow:
- `/speckit.specify` → creates `SPEC.md`
- `/speckit.plan` → creates `PLAN.md`
- `/speckit.tasks` → creates `TASKS.md`
- `/speckit.implement` → executes tasks

**Agent Team** wraps Spec Kit with:
- PM Agent that reads PRD and prioritizes features
- Orchestrator that drives the workflow state machine
- Mattermost integration for human-in-the-loop
- Worktree isolation for clean PRs

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/sbhavani/speckit-agents.git
cd speckit-agents
uv sync --dev

# 2. Configure
cp config.yaml config.local.yaml
# Edit config.local.yaml with your Mattermost and API tokens

# 3. Validate setup
uv run python orchestrator.py --doctor

# 4. Run a feature
uv run python orchestrator.py --feature "Add user authentication"
```

## How It Works

🦉 **PM Agent** reads the project's PRD and suggests the highest-priority unimplemented feature.

👀 **Human** approves or rejects the suggestion in Mattermost.

🦊 **Dev Agent** runs the Spec Kit workflow:
1. `/speckit.specify` → creates SPEC.md
2. `/speckit.plan` → creates PLAN.md
3. `/speckit.tasks` → creates TASKS.md
4. `/speckit.implement` → executes all tasks

❓ During implementation, the Dev Agent can ask questions. PM Agent answers based on PRD context.

✅ Human can intervene, ask questions, or approve/reject at any checkpoint.

🔀 Dev Agent creates a PR from an isolated worktree.

📖 PM Agent records learnings to `.agent/product-manager.md`.

## CLI Reference

```bash
# Normal workflow (PM suggests feature)
uv run python orchestrator.py

# Dry run (prints to stdout, no Mattermost)
uv run python orchestrator.py --dry-run

# Skip PM, implement specific feature
uv run python orchestrator.py --feature "Add user authentication"

# Simple mode (skip spec/plan/tasks phases)
uv run python orchestrator.py --feature "Add fix" --simple

# Resume from last state
uv run python orchestrator.py --resume

# Resume and auto-approve
uv run python orchestrator.py --approve

# Loop mode (run multiple features)
uv run python orchestrator.py --loop

# Target specific project
uv run python orchestrator.py --project finance-agent

# Start responder (listens for /suggest and @mentions)
uv run python responder.py

# Start workers
uv run python worker.py --consumer worker-1
uv run python worker_pool.py --workers 3
```

### Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Print to stdout, no Mattermost |
| `--feature "X"` | Skip PM, implement feature X |
| `--simple` | Skip spec/plan/tasks phases |
| `--resume` | Resume from last phase |
| `--approve` | Resume and auto-approve (skip review) |
| `--loop` | Run multiple features |
| `--project X` | Target project from config |
| `--channel X` | Override Mattermost channel ID |
| `--doctor` | Validate setup |
| `--version` | Print version and exit |
| `--show-state` | Print current state and exit |
| `--verbose` | Debug logging |
| `--log-level X` | Set logging level (DEBUG, INFO, WARNING, ERROR) |
| `--tools` | Enable tool-augmented discovery/validation hooks |
| `--no-tools` | Disable tool-augmented hooks |
| `--config X` | Path to config file (default: config.yaml) |

## Architecture

![Overview](docs/overview.png)

## Configuration

```yaml
projects:
  finance-agent:
    path: /path/to/finance-agent
    prd_path: docs/PRD.md
    channel_id: <channel-id>

openclaw:
  ssh_host: localhost
  openclaw_account: productManager
  anthropic_base_url: https://api.minimax.io/anthropic
  anthropic_model: MiniMax-M2.1

mattermost:
  url: "http://localhost:8065"
  channel_id: <channel-id>
  dev_bot_user_id: <user-id>
  pm_bot_user_id: <user-id>

redis_streams:
  url: "redis://localhost:6379"
  stream: "feature-requests"
  consumer_group: "orchestrator-workers"
  defaults:
    max_length: 10000
    block_ms: 5000

workflow:
  approval_timeout: 300
  auto_approve: false
  tool_augmentation:
    enabled: false
```

Override locally with `config.local.yaml` (gitignored).

## Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)
- [Claude Code CLI](https://claude.com/claude-code) — authenticated
- [GitHub CLI](https://cli.github.com/) (`gh`)
- [Mattermost](https://mattermost.com/) server (self-hosted chat, like Slack)
- Redis (optional, for state persistence)

## Docker Deployment

```bash
# Start services
docker compose -f deploy/docker-compose.yml up -d
```

## Files

| File | Description |
|------|-------------|
| `orchestrator.py` | Main workflow state machine |
| `responder.py` | Listens for /suggest commands and @mentions |
| `worker.py` | Redis Streams consumer |
| `worker_pool.py` | Parallel worker spawner with auto-restart |
| `mattermost_bridge.py` | Dual-bot Mattermost API client |
| `state_redis.py` | Redis-backed state persistence |
| `tool_augment.py` | Pre/post phase discovery and validation hooks |
| `analyze_augment.py` | JSONL log analysis for augmentation metrics |
| `src/redis_streams/` | Redis Streams library (consumer, producer, checkpoint, monitoring) |
| `.claude/agents/pm-agent.md` | PM Agent definition |
| `.claude/agents/dev-agent.md` | Dev Agent definition |
| `docs/SETUP.md` | Setup guide |
| `docs/PRD.md` | Product requirements |
| `deploy/` | Docker deployment files |

## Documentation

- [Setup Guide](docs/SETUP.md) — Full setup walkthrough
- [PRD](docs/PRD.md) — Product requirements (user stories)
- [Workflow](docs/WORKFLOW.md) — Phase details
- [Architecture](docs/ARCHITECTURE.md) — System design
- [Config Reference](docs/CONFIG.md) — Configuration options

## Maintainers

- [@PardisTaghavi](https://github.com/PardisTaghavi)
- [@sbhavani](https://github.com/sbhavani)

## License

[MIT](LICENSE)
