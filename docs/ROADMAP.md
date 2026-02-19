# Roadmap

Future enhancements and prioritized features.

## MoSCoW Roadmap

### Must Have (Critical)
- [ ] **Error recovery**: Improve handling of corrupted state files
- [ ] **Timeout handling**: More robust Claude timeout management

### Should Have (Important)
- [ ] **Slash commands + Webhooks**: Trigger workflows from Mattermost via slash command
- [ ] **Metrics dashboard**: Track features shipped, time-to-PR, questions asked

### Could Have (Nice to Have)
- [ ] **Multiple Dev Agents**: Fan out parallel Spec Kit phases
- [ ] **Code Review Agent**: Review PR before posting
- [ ] **Hatchet integration**: Background task queue

### Won't Have (Not for now)
- **Temporal**: Enterprise workflow orchestration - overkill
- **Full multi-agent parallelism**: Limited benefit currently

## Prioritized Feature List

### P1: Core Workflow

| Feature | Description | Effort |
|---------|-------------|--------|
| Parallel task execution | Run [P] marked tasks concurrently | ✅ Done |
| Enhanced resume | Better state recovery | Small |
| Config validation | Startup checks | Small |

### P2: UX

| Feature | Description | Status |
|---------|-------------|--------|
| Phase duration display | Time per phase in summary | ✅ Done |
| Progress emoji | ✅ ❌ 🔄 on completions | |
| Color output | ANSI colors | |
| Verbose mode | `--verbose` flag | ✅ Done |
| Config doctor | `--doctor` flag | ✅ Done |

### P3: Developer Experience

| Feature | Description | Effort |
|---------|-------------|--------|
| Hot reload | Watch config, restart | Small |
| Template projects | `--template` flag | Small |
| Local dev mode | Skip git worktree | Small |
| Mock mode | `--mock-llm` for testing | Medium |

### P4: Observability

| Feature | Description | Effort |
|---------|-------------|--------|
| Structured logs | JSON logging | Small |
| Metrics export | Prometheus endpoint | Medium |
| Trace IDs | Correlation IDs | Small |
| Health check | HTTP endpoint | Small |

### P5: Advanced

| Feature | Description | Effort |
|---------|-------------|--------|
| Auto-scaling workers | K8s HPA | Large |
| Scheduled runs | Cron-like | Medium |
| Feature branching | Auto naming | Small |
| PR templates | Custom body | Tiny |

## Testing Strategy

1. **Unit tests** - Test in isolation with mocks
2. **Integration tests** - Test with real Redis/Mattermost
3. **Manual testing** - Dry-run mode for validation
4. **Load testing** - Concurrent workers

## Performance Notes

- Phase timeouts: 60min each
- Mattermost poll: 15s interval
- Retry backoff: 5s, 20s, 80s

## Lessons Learned

From first AI-generated feature (Redis Streams):

1. **Good**: 25 min from suggestion to PR
2. **Good**: Generated 25 files with good structure
3. **Issue**: Syntax errors in generated code
4. **Fix**: Run Python syntax check before PR
5. **Fix**: Add mypy type checking to CI
