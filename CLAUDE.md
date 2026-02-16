# CLAUDE.md

## Project Overview

Agent Team — A multi-agent orchestration system where a Product Manager agent and Developer agent collaborate to ship features. Communication happens through Mattermost via OpenClaw. Human operator can intervene at any time.

## Architecture

- `orchestrator.py` — Main workflow state machine (PM suggest → Review → Dev specify/plan/tasks/implement → PR)
- `mattermost_bridge.py` — OpenClaw CLI wrapper for Mattermost messaging (over SSH)
- `.claude/agents/pm-agent.md` — PM Agent subagent definition
- `.claude/agents/dev-agent.md` — Developer Agent subagent definition
- `config.yaml` — Configuration (project path, OpenClaw settings, timeouts)
- `docs/PRD.md` — Full product requirements document

## Commands

```bash
# Run the orchestrator (posts to Mattermost)
python orchestrator.py

# Dry run (prints to stdout, no Mattermost)
python orchestrator.py --dry-run

# Loop mode (keeps suggesting features after each PR)
python orchestrator.py --loop

# Custom config
python orchestrator.py --config config.local.yaml
```

## Key Dependencies

- Claude Code CLI (`claude`) — must be installed and authenticated
- OpenClaw on `sb@mac-mini-i7.local` — Mattermost bridge
- GitHub CLI (`gh`) — for PR creation
- Python 3.10+ with pyyaml

## Target Project

The orchestrator works on `/Users/sbhavani/code/finance-agent` by default (configurable in config.yaml). That project must have speckit commands in `.claude/commands/`.
