# CLAUDE.md

## Project Overview

Agent Team — A multi-agent orchestration system where a Product Manager agent and Developer agent collaborate to ship features. Communication happens through Mattermost. Human operator can intervene at any time.

## Architecture

- `orchestrator.py` — Main workflow state machine (PM suggest → Review → Dev specify/plan/tasks/implement → PR)
- `mattermost_bridge.py` — Mattermost API bridge for messaging
- `.claude/agents/pm-agent.md` — PM Agent subagent definition
- `.claude/agents/dev-agent.md` — Developer Agent subagent definition
- `config.yaml` — Configuration (project path, Mattermost, timeouts)
- `docs/SETUP.md` — Setup guide (Mattermost, Redis, bots)
- `docs/PRD.md` — Product requirements (user stories, acceptance criteria)
- `docs/WORKFLOW.md` — End-to-end workflow details
- `docs/ARCHITECTURE.md` — System components and design
- `docs/ROADMAP.md` — Future enhancements
- `docs/CONFIG.md` — Configuration reference

## Commands

```bash
# Setup
uv sync --dev

# Run the orchestrator (posts to Mattermost)
uv run python orchestrator.py

# Dry run (prints to stdout, no Mattermost)
uv run python orchestrator.py --dry-run

# Loop mode (keeps suggesting features after each PR)
uv run python orchestrator.py --loop

# Skip PM, implement a specific feature
uv run python orchestrator.py --feature "Add user authentication"

# Resume after crash/interrupt
uv run python orchestrator.py --resume

# Custom config
uv run python orchestrator.py --config config.local.yaml

# Tests
uv run pytest tests/ -m "not integration"    # unit tests only
uv run pytest tests/ -m integration           # live Mattermost tests
uv run pytest tests/                          # all tests
```

## Key Dependencies

- **uv** — dependency management
- **Claude Code CLI** (`claude`) — must be installed and authenticated
- **GitHub CLI** (`gh`) — for PR creation
- **Redis** — for state persistence (optional)
- Python 3.10+

## Docker Deployment

Dockerfiles and docker-compose for containerized deployment are in `deploy/`.

## Configuration

All environment-specific values live in `config.yaml` (channel IDs, tokens, SSH hosts, etc.).
Override locally with `config.local.yaml` (gitignored).

## Target Project

The orchestrator works on `/Users/sbhavani/code/finance-agent` by default (configurable in config.yaml). That project must have speckit commands in `.claude/commands/`.

## Git Conventions

- Use **conventional commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- Do NOT add `Co-Authored-By` lines to commit messages
- Keep subject line under 72 characters
- Use imperative mood in subject ("add feature" not "added feature")

## Active Technologies
- Redis 5.0+ (for Streams API), redis-py or equivalent client library (004-redis-streams)
- Redis (stream storage), optional: metadata store for consumer offsets (004-redis-streams)
- Python 3.10+ (from CLAUDE.md requirement) + mattermost_bridge (Mattermost API), state_redis (Redis state), tool_augment (context augmentation), yaml (config) (001-emoji-markers)
- Redis for workflow state persistence, YAML for configuration (001-emoji-markers)

## Recent Changes
- 004-redis-streams: Added Redis 5.0+ (for Streams API), redis-py or equivalent client library
