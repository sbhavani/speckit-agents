# Experiment Pipeline — Tool-Augmented Multi-Agent Evaluation

Evaluation data for the ACM CAIS 2026 demo paper. Measures whether tool-augmented
discovery/validation hooks improve multi-agent software engineering quality.

## Prerequisites

- Python 3.10+ with `uv`
- `claude` CLI installed and authenticated
- `gh` CLI installed and authenticated
- Access to all 3 target project repos (paths configured in `config.yaml`)
- Redis running (for state persistence, optional with `--dry-run`)

## Setup

```bash
# On the projects machine, pull experiment code
git fetch origin && git checkout experiments
uv sync --dev

# Verify config paths match this machine
cat config.yaml  # check projects.*.path entries
```

## Running the Experiment

### Full run (30 experiments: 15 features x 2 conditions)

```bash
uv run python experiment_runner.py
```

Expected runtime: ~5-8 hours (each run takes 10-15 min).

### Selective runs

```bash
# Single project (10 runs)
uv run python experiment_runner.py --project finance-agent

# Single feature (2 runs: baseline + augmented)
uv run python experiment_runner.py --feature-id fin-01

# Preview without executing
uv run python experiment_runner.py --dry-run
```

### Resume after interruption

```bash
uv run python experiment_runner.py --resume
```

Skips any feature+condition pair that already has a completed results directory.

## Quality Scoring

After runs complete, score with LLM-as-judge:

```bash
# Score all unscored runs
uv run python quality_evaluator.py

# Re-score everything (overwrites existing scores)
uv run python quality_evaluator.py --re-score
```

## Analysis

```bash
# Summary to stdout
uv run python analyze_augment.py --experiment

# Paper-ready markdown tables
uv run python analyze_augment.py --experiment --markdown

# ASCII comparison charts
uv run python analyze_augment.py --experiment --charts

# Raw JSON for further processing
uv run python analyze_augment.py --experiment --json
```

## Output Structure

```
experiments/
  features.yaml              # Feature definitions (checked in)
  results/
    fin-01_baseline_20260219T.../
      stdout.log             # Orchestrator stdout
      stderr.log             # Orchestrator stderr
      metadata.json          # Timing, exit code, feature info
      quality.json           # LLM-as-judge scores (after evaluation)
    fin-01_augmented_20260219T.../
      stdout.log
      stderr.log
      metadata.json
      quality.json
      run_*.jsonl            # Augmentation log (augmented runs only)
    summary_*.json           # Per-batch run summary
```

## Metrics

**Quality dimensions** (1-5 scale, LLM-as-judge):
- **Completeness**: All requirements addressed?
- **Correctness**: Technically sound decisions?
- **Consistency**: Follows existing codebase conventions?
- **Code Quality**: Clean, tested, documented?

**Overhead**: Duration delta between baseline and augmented conditions.

**Validation**: Per-phase pass/fail rates from augmentation hooks.
