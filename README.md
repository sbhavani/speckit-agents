# Spec Kit Agent Team

A multi-agent orchestration system where a **Product Manager agent** and **Developer agent** collaborate to ship features autonomously. Communication happens through Mattermost via OpenClaw, with a human operator able to observe and intervene at any time.

Both agents are powered by Claude Code CLI (`claude -p`) running in headless mode. The Developer agent uses **[Spec Kit](https://github.com/github/spec-kit)** for structured feature specification and implementation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Mattermost Channel                        │
│                                                              │
│   Human           PM Agent            Dev Agent              │
│   (intervene)     (answer Qs)         (spec, build,        │
│                                            create PR)        │
└──────────────────────────┬──────────────────────────────────┘
                           │
              Mattermost API (http://localhost:8065)
                           │
┌──────────────────────────┴──────────────────────────────────┐
│              Local Services (uv)                             │
│                                                           │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐   │
│  │  Responder  │───▶│ Orchestrator │───▶│   Claude   │   │
│  │ (listens)  │    │  (workflow)  │    │   CLI       │   │
│  └─────────────┘    └──────────────┘    └─────────────┘   │
│        │                   │                   │              │
│        ▼                   ▼                   ▼              │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐   │
│  │   Redis     │    │  Worktree    │    │ Target Repo │   │
│  │  (docker)  │    │  /tmp/       │    │  (branch)   │   │
│  └─────────────┘    └──────────────┘    └─────────────┘   │
│                          │                                  │
│                          └── Each workflow gets:             │
│                              • Isolated worktree in /tmp/   │
│                              • Feature branch for PR        │
│                              • Cleaned up after PR          │
└─────────────────────────────────────────────────────────────┘

State Machine (Orchestrator):
INIT → PM_SUGGEST → REVIEW → DEV_SPECIFY → DEV_PLAN → DEV_TASKS
→ PLAN_REVIEW → DEV_IMPLEMENT → CREATE_PR → PM_LEARN → DONE
```

## Quick Start

```bash
# Setup
uv sync --dev

# Start Redis (for caching)
docker compose up -d redis

# Run the responder (listens for /suggest and @mentions)
uv run python responder.py

# In another terminal: run the orchestrator (usually spawned by responder)
uv run python orchestrator.py --project live-set-revival

# Dry run (prints to stdout, no Mattermost)
uv run python orchestrator.py --dry-run

# Skip PM, implement a specific feature
uv run python orchestrator.py --feature "Add user authentication"

# Resume after crash/interrupt
uv run python orchestrator.py --resume

# Loop mode (keeps suggesting features after each PR)
uv run python orchestrator.py --loop

# Run tests
uv run pytest tests/

# New CLI Flags
uv run python orchestrator.py --version                    # Print version
uv run python orchestrator.py --show-state                 # Show saved state
uv run python orchestrator.py --log-level DEBUG           # Set log level
uv run python orchestrator.py --verbose                   # Verbose output (DEBUG)
uv run python orchestrator.py --doctor                    # Validate config
uv run python orchestrator.py --feature "Add X" --simple # Simple mode (skip spec/plan)

# Parallel Workflows (via Redis Streams)
uv run python worker.py --consumer worker1                # Run a worker
uv run python worker_pool.py --workers 3                  # Run 3 workers
```

## Configuration

All configuration lives in `config.yaml`:

```yaml
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
  ssh_host: localhost
  openclaw_account: productManager
  anthropic_api_key: sk-cp-...  # Minimax API key for responder PM questions
  anthropic_base_url: https://api.minimax.io/anthropic
  anthropic_model: MiniMax-M2.1

mattermost:
  channel_id: bhpbt6h4xtnem8int5ccmbo4dw
  url: "http://localhost:8065"
  dev_bot_token: ...
  dev_bot_user_id: ...
  pm_bot_token: ...
  pm_bot_user_id: ...

workflow:
  approval_timeout: 300
  question_timeout: 120
  plan_review_timeout: 60
  auto_approve: false
  loop: false
  impl_poll_interval: 15
  user_mention: ""
```

Override locally with `config.local.yaml` (gitignored).

## Mattermost Commands

**Orchestrator (during workflow):**
- **approve** / **reject** — Approve or reject feature suggestions
- **yolo** — Skip plan review and start implementation immediately
- **/feature "Feature name"** — Skip PM and directly implement a feature

**Responder (always listening):**
- **/suggest** — Start feature suggestion workflow
- **/suggest "Feature name"** — Start implementation of specific feature
- **@product-manager <question>** — Ask PM questions (includes PRD context)

## How It Works

1. **PM_SUGGEST**: PM Agent reads the project's PRD, analyzes what's already implemented, and suggests the highest-priority feature
2. **REVIEW**: Feature suggestion is posted to Mattermost for human approval
3. **DEV_SPECIFY**: Dev Agent runs `/speckit.specify` to create SPEC.md
4. **DEV_PLAN**: Dev Agent runs `/speckit.plan` to create PLAN.md
5. **DEV_TASKS**: Dev Agent runs `/speckit.tasks` to create TASKS.md
6. **PLAN_REVIEW**: Human can ask questions or reject before implementation (60s yolo window)
7. **DEV_IMPLEMENT**: Dev Agent runs `/speckit.implement`. If questions arise, PM Agent answers them
8. **CREATE_PR**: Dev Agent creates a branch, commits changes, and opens a PR
9. **PM_LEARN**: PM Agent writes learnings to `.agent/product-manager.md` journal

### Worktree Isolation

Each workflow runs in an isolated **git worktree** (in `/tmp/`) with its own **feature branch**:

```
/tmp/agent-team-live-set-revival-20260217-120000/
├── src/          # Copy of the repo (worktree)
├── .git          # Points to main repo's .git (shared objects)
└── (worktree files)

Branch: agent-worktree-20260217-120000  ← PR created from this branch
```

- **Worktree**: Isolated working directory (doesn't touch your main repo)
- **Branch**: Feature branch for the PR (created fresh each workflow)
- **Fast**: Worktrees share `.git` objects with main repo (no full clone)
- **Cleanup**: Worktree and branch deleted after PR is created

## Prerequisites

- **[uv](https://github.com/astral-sh/uv)** — Python dependency management
- **[Docker](https://www.docker.com/)** — For Redis service
- **[Redis](https://redis.io/)** — Cache and session state (via Docker)
- **[Claude Code CLI](https://claude.com/claude-code)** — AI assistant, must be installed and authenticated
- **[GitHub CLI](https://cli.github.com/)** (`gh`) — For PR creation
- **[Python 3.10+](https://www.python.org/)**
- **[Mattermost](https://mattermost.com/)** — Running at http://localhost:8065
- **[Spec Kit](https://github.com/github/spec-kit)** — Installed in target project's `.claude/commands/`

## Docker Deployment

For production, run as docker-compose services:

```bash
# Start all services
docker compose up -d

# Start just the responder (listens for /suggest)
docker compose up -d responder

# Manually trigger orchestrator
docker compose run --rm orchestrator --project live-set-revival
```

Services:
- **redis** — Cache and session state
- **responder** — Listens for `/suggest` and @mentions, spawns workflows
- **orchestrator** — Runs the feature workflow (spawned by responder)

## Files

- `orchestrator.py` — Main workflow state machine
- `responder.py` — Listens for /suggest and @mentions, spawns workflows
- `worker.py` — Redis Streams consumer for parallel workflows
- `worker_pool.py` — Spawns multiple worker processes
- `mattermost_bridge.py` — Mattermost communication (OpenClaw CLI + API)
- `state_redis.py` — Redis-backed state storage
- `docker-compose.yml` — Docker services (redis, responder, orchestrator)
- `.claude/agents/pm-agent.md` — PM Agent definition
- `.claude/agents/dev-agent.md` — Developer Agent definition
- `config.yaml` — Configuration
- `docs/PRD.md` — Full product requirements document

## Redis Streams Module

This project includes a Redis Streams module (`src/redis_streams/`) for event-driven architecture, replacing polling-based inter-service communication.

### Installation

The module requires Redis 5.0+ and the redis-py client:

```bash
pip install redis
```

### Quick Start

```python
from redis_streams.producer import StreamProducer, StreamManager
from redis_streams.consumer import StreamConsumer, ConsumerGroupManager

# Create a stream
manager = StreamManager("redis://localhost:6379")
manager.create_stream("events", retention_ms=86400000)
manager.close()

# Produce events
producer = StreamProducer(
    redis_url="redis://localhost:6379",
    stream_name="events"
)
message_id = producer.publish(
    event_type="data.update",
    payload={"symbol": "AAPL", "price": 150.25}
)
producer.close()

# Consume events
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="events",
    group="my-group",
    consumer="consumer-1"
)

def handle_event(event):
    print(f"Received: {event.payload}")
    return True  # Acknowledge

consumer.subscribe(handle_event)
```

### Checkpoint & Resume

Enable checkpoint persistence to resume from the last processed message after restart:

```python
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="events",
    group="my-group",
    consumer="consumer-1",
    enable_checkpoint=True  # Persists position to Redis
)
```

### Consumer Groups

Consumer groups enable multiple consumers to process the same stream independently:

```python
# Create group with start position
manager = ConsumerGroupManager("redis://localhost:6379")
manager.create_group("events", "processors", start_id="0")  # "0" = from beginning, "$" = new only

# Multiple consumers in the same group
c1 = StreamConsumer(stream="events", group="processors", consumer="worker-1")
c2 = StreamConsumer(stream="events", group="processors", consumer="worker-2")
```

### API Reference

**Producer:**
- `StreamProducer.publish(event_type, payload, metadata)` - Publish event to stream
- `StreamManager.create_stream(name, retention_ms, max_length)` - Create stream
- `StreamManager.delete_stream(name)` - Delete stream

**Consumer:**
- `StreamConsumer.subscribe(callback)` - Start consuming (blocking)
- `StreamConsumer.acknowledge(message_id)` - Acknowledge processed message
- `StreamConsumer.get_pending()` - Get unacknowledged messages
- `ConsumerGroupManager.create_group(stream, group, start_id)` - Create consumer group

### Configuration

```python
# Consumer options
consumer = StreamConsumer(
    redis_url="redis://localhost:6379",
    stream="events",
    group="my-group",
    consumer="consumer-1",
    block_ms=5000,           # Blocking timeout (ms)
    count=10,                # Max messages per fetch
    auto_ack=False,          # Auto-ack after callback
    enable_checkpoint=True, # Enable checkpoint persistence
    enable_reclaim=False,    # Enable stale message reclaim
    reclaim_interval_ms=30000,  # Reclaim loop interval
    reclaim_min_idle_ms=30000   # Min idle time before reclaim
)
```

### Monitoring

```python
from redis_streams.monitoring import get_stream_metrics, get_group_metrics

metrics = get_stream_metrics("redis://localhost:6379", "events")
print(f"Stream length: {metrics['length']}")
print(f"First entry: {metrics['first_entry']}")
```
