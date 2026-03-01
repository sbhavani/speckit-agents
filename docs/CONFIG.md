# Configuration

Configuration reference for speckit-agents.

## config.yaml

All environment-specific values in `config.yaml`. Override locally with `config.local.yaml` (gitignored).

```yaml
# Multi-project mode
projects:
  finance-agent:
    path: /Users/sb/code/finance-agent
    prd_path: docs/PRD.md
    channel_id: <channel-id>

# LLM Configuration (Anthropic-compatible API)
llm:
  api_key: sk-cp-...
  base_url: https://api.minimax.io/anthropic
  model: MiniMax-M2.1

mattermost:
  url: "http://localhost:8065"
  dev_bot_token: <token>
  dev_bot_user_id: <user_id>
  pm_bot_token: <token>
  pm_bot_user_id: <user_id>

workflow:
  approval_timeout: 300
  question_timeout: 120
  plan_review_timeout: 60
  auto_approve: false
  loop: false
  impl_poll_interval: 15
  user_mention: ""
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude Code auth | - |
| `AGENT_TEAM_CONFIG` | Config path | `./config.yaml` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `HOST_WORKDIR` | Docker path mapping | - |
| `CLAUDE_BIN` | Claude CLI path | `~/.local/bin/claude` |

## Mattermost Setup

- **Server**: `http://localhost:8065`
- **Dev bot**: `dev-agent` - automation bot for implementation
- **PM bot**: `product-manager` - separate identity for PM messages
- **Channel**: One channel per project (create via Mattermost UI or API)

## Redis Keys

| Key Pattern | Value | TTL |
|-------------|-------|-----|
| `prd:{project}:{path}` | PRD content | 1 hour |
| `session:{session_id}` | State | 24 hours |
| `channel:{id}:project` | Config | 1 hour |

## CLI Options

```bash
python orchestrator.py --config config.yaml   # Custom config
python orchestrator.py --dry-run              # Print to stdout
python orchestrator.py --loop                 # Run multiple features
python orchestrator.py --feature "Add X"     # Skip PM
python orchestrator.py --simple              # Skip specify/plan/tasks
python orchestrator.py --resume              # Resume from state
python orchestrator.py --project name         # Target project
python orchestrator.py --doctor               # Validate setup
python orchestrator.py --verbose              # Debug logging
python orchestrator.py --tools               # Enable tool augmentation
python orchestrator.py --no-tools            # Disable tool augmentation
```
