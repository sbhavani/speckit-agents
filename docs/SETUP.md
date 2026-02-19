# Setup Guide

How to set up agent-team from scratch.

## Prerequisites

- Python 3.10+
- Redis (running locally or accessible)
- Mattermost server
- Claude Code CLI (`claude`)
- GitHub CLI (`gh`)

## Quick Start

```bash
# Clone and setup
git clone https://github.com/sbhavani/speckit-agents.git
cd speckit-agents
uv sync --dev

# Copy and edit config
cp config.yaml config.local.yaml
# Edit config.local.yaml with your tokens

# Validate setup
uv run python orchestrator.py --doctor
```

## Mattermost Setup

### Overview

agent-team communicates with Mattermost via its REST API. OpenClaw is optional—it's one way to send messages, but you can also use the API directly.

### Option 1: Direct API (Recommended)

The simplest setup uses Mattermost's REST API directly:

1. Create bots in Mattermost
2. Get their tokens
3. Configure in `config.yaml`

```yaml
mattermost:
  url: "http://localhost:8065"
  channel_id: <your-channel-id>
  dev_bot_token: <bot-token>
  dev_bot_user_id: <bot-user-id>
  pm_bot_token: <pm-bot-token>
  pm_bot_user_id: <pm-bot-user-id>
```

### Option 2: OpenClaw Bridge

OpenClaw provides SSH-based access to Mattermost. Use this if you already have OpenClaw configured:

```yaml
openclaw:
  ssh_host: localhost  # SSH server with OpenClaw
```

When using OpenClaw, the orchestrator can still read messages via the API directly—OpenClaw is only needed for sending.

### Creating Bots

1. **Create a bot user**:
   - Go to Mattermost → Integrations → Bot Accounts
   - Or use the API: `POST /api/v4/bots`

2. **Get the bot token**:
   - Copy the token shown after creation
   - Or create via API: `POST /api/v4/users/tokens`

3. **Get the bot user ID**:
   - Use the API: `GET /api/v4/users/by_username/{username}`
   - Or check the bot details page

4. **Add bot to channel**:
   - Invite the bot to your channel
   - Or use: `POST /api/v4/channels/{channel_id}/members`

### Getting Channel ID

1. Open the channel in Mattermost
2. Click channel name → View Info
3. Copy the Channel ID

Or use the API:
```bash
curl -H "Authorization: Bearer <admin-token>" \
  "http://localhost:8065/api/v4/teams/<team-id>/channels/name/<channel-name>"
```

## Redis Setup

### Option 1: Local Redis (Recommended for Development)

```bash
# Install Redis via Homebrew
brew install redis
brew services start redis

# Or on Linux
sudo apt install redis-server
sudo systemctl start redis
```

### Option 2: Docker Redis

```bash
# Run Redis in background
docker run -d -p 6379:6379 redis:7-alpine
```

### Verify Redis

```bash
redis-cli ping
# Should return: PONG
```

The orchestrator will use Redis if `redis_url` is configured in config.yaml, otherwise falls back to file-based state storage.

## Configuration

### Required Config

```yaml
projects:
  my-project:
    path: /path/to/project
    prd_path: docs/PRD.md
    channel_id: <channel-id>

mattermost:
  url: "http://localhost:8065"
  channel_id: <channel-id>
  dev_bot_token: <token>
  dev_bot_user_id: <user-id>
  pm_bot_token: <token>
  pm_bot_user_id: <user-id>
```

### Optional Config

```yaml
# Workflow timeouts (seconds)
workflow:
  approval_timeout: 300
  question_timeout: 120
  plan_review_timeout: 60
  auto_approve: false
  loop: false

# Redis for state persistence
redis_url: redis://localhost:6379
```

### Local Overrides

Create `config.local.yaml` for local overrides (gitignored):

```yaml
mattermost:
  dev_bot_token: my-dev-token
  pm_bot_token: my-pm-token
```

## Testing

```bash
# Dry run (no Mattermost)
uv run python orchestrator.py --dry-run

# Validate setup
uv run python orchestrator.py --doctor

# Run with verbose logging
uv run python orchestrator.py --verbose
```

## Troubleshooting

### "Bot not found" error
- Verify bot exists: `GET /api/v4/users/<user_id>`
- Check bot is activated in Mattermost admin console

### "Channel not found" error
- Verify channel ID is correct
- Ensure bot is a member of the channel

### "Token invalid" error
- Regenerate bot token in Mattermost
- Ensure token has correct scopes

### Messages not posting
- Check bot has `post` permission
- Verify channel ID matches
- Check Mattermost logs for errors
