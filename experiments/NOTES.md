# Experiment Notes

## Future Experiments

### Full Speckit vs Simple Mode Comparison

Add a third condition to compare full speckit workflow vs simple mode:

| Condition | Description | Flag | Time per run |
|-----------|-------------|------|--------------|
| **baseline** | Standard Claude, no tools | `--no-tools` | ~10 min |
| **augmented** | Claude + tool hooks, simple mode | `--tools --simple` | ~12 min |
| **full** | Full specify→plan→tasks→implement | `--tools` (no --simple) | ~30+ min |

**Research Question:** Does the full speckit workflow (specify, plan, tasks phases) produce better quality code than simple mode?

**Pros:**
- Answers key paper question: "Is speckit workflow worth the extra time?"
- More realistic for production use
- Shows value of specification/planning phases

**Cons:**
- 3x experiment runtime (8 features × 3 = 24 runs per project)
- Each run takes ~30+ minutes

**Implementation:**
- Add "full" to CONDITIONS in experiment_runner.py
- Remove --simple flag for full condition
- Estimated total runtime: ~12 hours for one project

---

## Completed Experiments

### finance-agent (2026-02-21)

8 features × 2 conditions = 16 runs

**Results:**
- Baseline avg: C=1.8 R=2.0 S=2.3 Q=1.8
- Augmented avg: C=2.2 R=2.2 S=2.5 Q=2.0
- Improvement: +0.3 across all dimensions

**Key Findings:**
- fin-03 (integration tests): +1.2 improvement with augmentation
- fin-06 (web UI): +3.0 improvement (baseline timed out)
- fin-08 (caching): +0.5 improvement
- fin-04: Worse with augmentation (-1.0)
