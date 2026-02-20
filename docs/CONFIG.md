# Configuration

Configuration reference for agent-team.

## config.yaml

All environment-specific values in `config.yaml`. Override locally with `config.local.yaml` (gitignored).

```yaml
# Multi-project mode
projects:
  finance-agent:
    path: /Users/sb/code/finance-agent
    prd_path: docs/PRD.md
    channel_id: bhpbt6h6tnt3nrnq8yi6n9k7br

openclaw:
  ssh_host: localhost
  anthropic_api_key: sk-cp-...
  anthropic_base_url: https://api.minimax.io/anthropic
  anthropic_model: MiniMax-M2.1

mattermost:
  channel_id: bhpbt6h4xtnem8int5ccmbo4dw
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
  # Tool-augmented discovery and validation hooks (enabled by default)
  tool_augmentation:
    enabled: true              # Enable pre/post phase hooks
    pre_stages: true          # Run discovery before each phase
    post_stages: true         # Run validation after each phase
    run_tests_before_impl: true
    run_tests_after_impl: true
    timeout_per_hook: 120     # Seconds per Claude invocation
    log_dir: "logs/augment"   # JSONL log output directory
    redis_url: "redis://localhost:6379"  # Optional Redis for streaming
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
- **Dev bot**: `openclaw` (ID: `prmnsceu8bg8tm1kmb3zzhbdwr`)
- **PM bot**: `product-manager` (ID: `osnrc8yrpffifj56friubo5dxr`)
- **Channel**: `#product-dev` (ID: `bhpbt6h4xtnem8int5ccmbo4dw`)

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
python orchestrator.py --simple               # Skip specify/plan/tasks
python orchestrator.py --resume               # Resume from state
python orchestrator.py --project name          # Target project
python orchestrator.py --doctor                # Validate setup
python orchestrator.py --verbose              # Debug logging
python orchestrator.py --tools                # Enable tool augmentation
python orchestrator.py --no-tools             # Disable tool augmentation
```
