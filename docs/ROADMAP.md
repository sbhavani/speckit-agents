# Roadmap

Future enhancements beyond the completed PRD scope.

## Completed (from original PRD)

All P0–P3 user stories are implemented. See [PRD.md](PRD.md) for details.

Key milestones:
- Core workflow (PM suggest → Review → Dev specify/plan/tasks/implement → PR)
- Human intervention (@mention PM, structured questions, override)
- UX (phase timers, progress emoji, ANSI colors, `--doctor`)
- Parallel execution (Redis Streams, worker pool, `[P]` task markers, `--simple`)
- Resilience (Redis + file state, `--resume`, retry backoff)
- Observability (phase durations, tool augmentation JSONL logs)
- Slash command trigger (`responder.py` listens for `/suggest` and @mentions)

## Ideas (Unprioritized)

These are potential directions. None have user stories or acceptance criteria yet — they need to be scoped before work begins.

- **Code Review Agent**: Automated PR review before posting
- **Metrics dashboard**: Track features shipped, time-to-PR, questions asked
- **Multiple Dev Agents**: Fan out parallel Spec Kit phases across agents
- **Mock mode**: `--mock-llm` flag for testing without Claude
- **Structured logs**: JSONL output for log aggregation
- **Health check endpoint**: HTTP liveness/readiness for containerized deployments

## Won't Have

- **Temporal**: Enterprise workflow orchestration — overkill for current scale
- **Hatchet**: Background task queue — Redis Streams covers this
- **Auto-scaling workers (K8s HPA)**: No demand signal, manual scaling is sufficient

## Lessons Learned

From first AI-generated feature (Redis Streams):

1. **Good**: 25 min from suggestion to PR
2. **Good**: Generated 25 files with good structure
3. **Issue**: Syntax errors in generated code
4. **Fix**: Run Python syntax check before PR
5. **Fix**: Add mypy type checking to CI
