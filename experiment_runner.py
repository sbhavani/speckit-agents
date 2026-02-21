#!/usr/bin/env python3
"""Batch experiment runner for tool-augmented multi-agent evaluation.

Runs each feature under baseline (--no-tools) and augmented (--tools) conditions,
capturing stdout, stderr, timing, and augmentation logs.

Usage:
    uv run python experiment_runner.py                          # all 30 runs
    uv run python experiment_runner.py --project finance-agent  # 10 runs
    uv run python experiment_runner.py --feature-id fin-01      # 2 runs
    uv run python experiment_runner.py --resume                 # skip done
    uv run python experiment_runner.py --dry-run                # print plan only
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

EXPERIMENTS_DIR = Path(__file__).parent / "experiments"
RESULTS_DIR = EXPERIMENTS_DIR / "results"
FEATURES_FILE = EXPERIMENTS_DIR / "features.yaml"
AUGMENT_LOG_DIR = Path(__file__).parent / "logs" / "augment"
CONDITIONS = ["baseline", "augmented"]
SLEEP_BETWEEN_RUNS = 5


def load_features(path: Path = FEATURES_FILE) -> list[dict]:
    """Load feature definitions from YAML."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["features"]


def make_run_id(feature_id: str, condition: str) -> str:
    """Generate a unique run directory name."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{feature_id}_{condition}_{ts}_{short_uuid}"


def find_completed_runs(feature_id: str, condition: str) -> list[Path]:
    """Find existing result dirs for a feature+condition pair."""
    if not RESULTS_DIR.exists():
        return []
    prefix = f"{feature_id}_{condition}_"
    return [
        d for d in sorted(RESULTS_DIR.iterdir())
        if d.is_dir() and d.name.startswith(prefix)
        and (d / "metadata.json").exists()
    ]


def build_command(feature: dict, condition: str) -> list[str]:
    """Build the orchestrator subprocess command."""
    cmd = [
        sys.executable, "orchestrator.py",
        "--simple",  # Skip specify/plan/tasks phases, go straight to implement
        "--dry-run",
        "--feature", feature["description"],
        "--project", feature["project"],
    ]
    if condition == "baseline":
        cmd.append("--no-tools")
    else:
        cmd.append("--tools")
    return cmd


def run_single(feature: dict, condition: str, dry_run: bool = False) -> dict | None:
    """Execute one orchestrator run and capture outputs."""
    run_id = make_run_id(feature["id"], condition)
    run_dir = RESULTS_DIR / run_id

    cmd = build_command(feature, condition)

    if dry_run:
        print(f"  [dry-run] Would run: {' '.join(cmd)}")
        print(f"  [dry-run] Output to: {run_dir}")
        return None

    run_dir.mkdir(parents=True, exist_ok=True)

    # Clear augment logs before augmented runs so we capture only this run's logs
    latest_augment_logs = []
    if condition == "augmented":
        latest_augment_logs = list(AUGMENT_LOG_DIR.glob("run_*.jsonl")) if AUGMENT_LOG_DIR.exists() else []

    print(f"  Running: {' '.join(cmd[:6])}...")
    start = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min max per run
            cwd=Path(__file__).parent,
        )
        duration = time.monotonic() - start
        exit_code = result.returncode
        stdout_text = result.stdout
        stderr_text = result.stderr
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - start
        exit_code = -1
        stdout_text = (e.stdout or b"").decode("utf-8", errors="replace")
        stderr_text = (e.stderr or b"").decode("utf-8", errors="replace") + "\n[TIMEOUT after 1800s]"
    except Exception as e:
        duration = time.monotonic() - start
        exit_code = -2
        stdout_text = ""
        stderr_text = str(e)

    # Write outputs
    (run_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")

    # Copy augmentation logs for augmented runs
    if condition == "augmented" and AUGMENT_LOG_DIR.exists():
        new_logs = [
            f for f in AUGMENT_LOG_DIR.glob("run_*.jsonl")
            if f not in latest_augment_logs
        ]
        for log_file in new_logs:
            shutil.copy2(log_file, run_dir / log_file.name)

    # Write metadata
    metadata = {
        "run_id": run_id,
        "feature_id": feature["id"],
        "project": feature["project"],
        "category": feature["category"],
        "expected_complexity": feature["expected_complexity"],
        "description": feature["description"],
        "condition": condition,
        "command": cmd,
        "exit_code": exit_code,
        "duration_s": round(duration, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    status = "OK" if exit_code == 0 else f"EXIT {exit_code}"
    print(f"  Done [{status}] in {duration:.1f}s -> {run_dir.name}")
    return metadata


def run_experiment(
    features: list[dict],
    resume: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Run all features under both conditions."""
    results = []
    total = len(features) * len(CONDITIONS)
    completed = 0

    for feature in features:
        for condition in CONDITIONS:
            completed += 1
            label = f"[{completed}/{total}] {feature['id']} ({condition})"

            if resume and find_completed_runs(feature["id"], condition):
                print(f"{label} -- skipped (already done)")
                continue

            print(f"{label}")
            meta = run_single(feature, condition, dry_run=dry_run)
            if meta:
                results.append(meta)

            if not dry_run and completed < total:
                time.sleep(SLEEP_BETWEEN_RUNS)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run tool-augmented experiment batch"
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Filter to a specific project (e.g. finance-agent)",
    )
    parser.add_argument(
        "--feature-id", type=str, default=None,
        help="Filter to a specific feature ID (e.g. fin-01)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip runs that already have results",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would run without executing",
    )
    parser.add_argument(
        "--features-file", type=str, default=None,
        help="Path to features YAML (default: experiments/features.yaml)",
    )
    args = parser.parse_args()

    features_path = Path(args.features_file) if args.features_file else FEATURES_FILE
    features = load_features(features_path)

    # Apply filters
    if args.project:
        features = [f for f in features if f["project"] == args.project]
    if args.feature_id:
        features = [f for f in features if f["id"] == args.feature_id]

    if not features:
        print("No features match the given filters.", file=sys.stderr)
        sys.exit(1)

    n_runs = len(features) * len(CONDITIONS)
    print(f"Experiment: {len(features)} features x {len(CONDITIONS)} conditions = {n_runs} runs")
    if args.dry_run:
        print("(DRY RUN - nothing will be executed)\n")
    print()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results = run_experiment(features, resume=args.resume, dry_run=args.dry_run)

    if results:
        ok = sum(1 for r in results if r["exit_code"] == 0)
        fail = len(results) - ok
        print(f"\nDone: {ok} succeeded, {fail} failed out of {len(results)} runs")

        # Write summary
        summary_path = RESULTS_DIR / f"summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
        summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
