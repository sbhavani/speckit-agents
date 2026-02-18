#!/usr/bin/env python3
"""Analyze tool-augmentation JSONL logs for research metrics.

Reads JSONL log files produced by ToolAugmentor and computes:
- Tool calls per phase and hook type
- Time overhead of augmentation
- Validation pass/fail rates
- Side-by-side comparison of augmented vs non-augmented runs

Usage:
    python analyze_augment.py logs/augment/run_*.jsonl
    python analyze_augment.py logs/augment/          # all logs in directory
    python analyze_augment.py --compare run1.jsonl run2.jsonl
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_records(path: Path) -> list[dict]:
    """Load all JSONL records from a file."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def analyze_run(records: list[dict]) -> dict:
    """Compute metrics for a single run's records."""
    tool_calls = [r for r in records if r["record_type"] == "tool_call"]
    hook_summaries = [r for r in records if r["record_type"] == "hook_summary"]
    run_summaries = [r for r in records if r["record_type"] == "run_summary"]

    # Tool calls per phase
    calls_by_phase = defaultdict(int)
    for tc in tool_calls:
        calls_by_phase[tc["phase"]] += 1

    # Time per hook
    time_by_hook = defaultdict(float)
    for hs in hook_summaries:
        key = f"{hs['phase']}/{hs['hook_type']}"
        time_by_hook[key] += hs["duration_ms"]

    # Validation pass/fail
    validations = []
    for hs in hook_summaries:
        findings = hs.get("findings", {})
        if "validation_passed" in findings:
            validations.append({
                "phase": hs["phase"],
                "hook_type": hs["hook_type"],
                "passed": findings["validation_passed"],
            })

    total_time_ms = sum(hs["duration_ms"] for hs in hook_summaries)
    pass_count = sum(1 for v in validations if v["passed"])
    fail_count = sum(1 for v in validations if not v["passed"])

    run_info = run_summaries[0] if run_summaries else {}

    return {
        "run_id": run_info.get("run_id", "unknown"),
        "outcome": run_info.get("outcome", "unknown"),
        "total_hooks": len(hook_summaries),
        "total_tool_calls": len(tool_calls),
        "total_time_ms": round(total_time_ms, 1),
        "total_time_s": round(total_time_ms / 1000, 1),
        "calls_by_phase": dict(calls_by_phase),
        "time_by_hook_ms": {k: round(v, 1) for k, v in time_by_hook.items()},
        "validations_passed": pass_count,
        "validations_failed": fail_count,
        "validation_rate": round(pass_count / max(pass_count + fail_count, 1), 2),
        "phases_augmented": run_info.get("phases_augmented", []),
    }


def print_analysis(metrics: dict) -> None:
    """Pretty-print analysis results."""
    print(f"Run: {metrics['run_id']}")
    print(f"Outcome: {metrics['outcome']}")
    print(f"Total hooks: {metrics['total_hooks']}")
    print(f"Total tool calls: {metrics['total_tool_calls']}")
    print(f"Total augmentation time: {metrics['total_time_s']}s")
    print(f"Phases augmented: {', '.join(metrics['phases_augmented']) or 'none'}")
    print()

    if metrics["calls_by_phase"]:
        print("Tool calls by phase:")
        for phase, count in sorted(metrics["calls_by_phase"].items()):
            print(f"  {phase}: {count}")
        print()

    if metrics["time_by_hook_ms"]:
        print("Time by hook (ms):")
        for hook, ms in sorted(metrics["time_by_hook_ms"].items()):
            print(f"  {hook}: {ms:.0f}ms")
        print()

    print(f"Validation: {metrics['validations_passed']} passed, "
          f"{metrics['validations_failed']} failed "
          f"({metrics['validation_rate']:.0%} pass rate)")


def compare_runs(metrics_list: list[dict]) -> None:
    """Print side-by-side comparison of multiple runs."""
    print(f"\n{'Metric':<30}", end="")
    for m in metrics_list:
        print(f"  {m['run_id'][:20]:<22}", end="")
    print()
    print("-" * (30 + 24 * len(metrics_list)))

    rows = [
        ("Outcome", "outcome"),
        ("Total hooks", "total_hooks"),
        ("Total tool calls", "total_tool_calls"),
        ("Total time (s)", "total_time_s"),
        ("Validations passed", "validations_passed"),
        ("Validations failed", "validations_failed"),
        ("Validation rate", "validation_rate"),
    ]

    for label, key in rows:
        print(f"{label:<30}", end="")
        for m in metrics_list:
            print(f"  {str(m[key]):<22}", end="")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze tool-augmentation JSONL logs")
    parser.add_argument("paths", nargs="+", help="JSONL files or directories to analyze")
    parser.add_argument("--compare", action="store_true", help="Compare multiple runs side-by-side")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Collect all JSONL files
    files: list[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("run_*.jsonl")))
        elif path.exists():
            files.append(path)
        else:
            print(f"Warning: {p} not found, skipping", file=sys.stderr)

    if not files:
        print("No JSONL files found.", file=sys.stderr)
        sys.exit(1)

    all_metrics = []
    for f in files:
        records = load_records(f)
        if records:
            metrics = analyze_run(records)
            all_metrics.append(metrics)

    if args.json:
        print(json.dumps(all_metrics, indent=2))
    elif args.compare and len(all_metrics) > 1:
        compare_runs(all_metrics)
    else:
        for i, metrics in enumerate(all_metrics):
            if i > 0:
                print("\n" + "=" * 60 + "\n")
            print_analysis(metrics)


if __name__ == "__main__":
    main()
