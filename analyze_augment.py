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
import math
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
    calls_by_phase: defaultdict = defaultdict(int)
    for tc in tool_calls:
        calls_by_phase[tc["phase"]] += 1

    # Time per hook
    time_by_hook: defaultdict = defaultdict(float)
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


## Experiment analysis functions ────────────────────────────────────


def load_experiment_results(results_dir: Path) -> list[dict]:
    """Load all metadata + quality + augment logs from experiment results."""
    results = []
    if not results_dir.exists():
        return results

    for run_dir in sorted(results_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        meta_path = run_dir / "metadata.json"
        if not meta_path.exists():
            continue

        entry = json.loads(meta_path.read_text(encoding="utf-8"))

        # Attach quality scores if available
        quality_path = run_dir / "quality.json"
        if quality_path.exists():
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            entry["quality"] = quality.get("scores")
            entry["quality_rationale"] = quality.get("rationale")
        else:
            entry["quality"] = None

        # Attach augment log metrics if available
        augment_logs = list(run_dir.glob("run_*.jsonl"))
        if augment_logs:
            records = load_records(augment_logs[0])
            entry["augment_metrics"] = analyze_run(records)
        else:
            entry["augment_metrics"] = None

        results.append(entry)

    return results


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Compute mean and standard deviation."""
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    if len(values) < 2:
        return mean, 0.0
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return mean, math.sqrt(variance)


def aggregate_by_condition(results: list[dict]) -> dict:
    """Compute mean +/- std per quality dimension per condition."""
    dims = ["completeness", "correctness", "consistency", "code_quality"]
    agg = {}

    for condition in ("baseline", "augmented"):
        scored = [
            r for r in results
            if r["condition"] == condition and r.get("quality")
        ]
        condition_agg = {"n": len(scored)}
        for dim in dims:
            vals = [r["quality"][dim] for r in scored if r["quality"].get(dim, 0) > 0]
            mean, std = _mean_std(vals)
            condition_agg[dim] = {"mean": round(mean, 2), "std": round(std, 2), "n": len(vals)}

        # Duration
        durations = [r["duration_s"] for r in scored if r.get("duration_s")]
        mean, std = _mean_std(durations)
        condition_agg["duration_s"] = {"mean": round(mean, 1), "std": round(std, 1)}

        agg[condition] = condition_agg

    return agg


def compute_overhead(results: list[dict]) -> dict:
    """Compute baseline vs augmented duration delta."""
    baseline_dur = [r["duration_s"] for r in results if r["condition"] == "baseline" and r.get("duration_s")]
    augmented_dur = [r["duration_s"] for r in results if r["condition"] == "augmented" and r.get("duration_s")]

    b_mean, _ = _mean_std(baseline_dur)
    a_mean, _ = _mean_std(augmented_dur)

    delta = a_mean - b_mean
    pct = (delta / b_mean * 100) if b_mean > 0 else 0.0

    return {
        "baseline_mean_s": round(b_mean, 1),
        "augmented_mean_s": round(a_mean, 1),
        "delta_s": round(delta, 1),
        "overhead_pct": round(pct, 1),
    }


def per_phase_quality(results: list[dict]) -> dict:
    """Compute validation pass rates per phase from augmented runs."""
    phase_stats: defaultdict = defaultdict(lambda: {"passed": 0, "failed": 0})

    for r in results:
        if r["condition"] != "augmented" or not r.get("augment_metrics"):
            continue
        # Re-read augment records for detailed phase info
        # Use the hook summary data already in augment_metrics
        metrics = r["augment_metrics"]
        for hook_key in metrics.get("time_by_hook_ms", {}):
            phase = hook_key.split("/")[0]
            # We only have aggregate pass/fail from analyze_run
            # so attribute based on total for now
            phase_stats[phase]  # ensure key exists

    # Build from augment_metrics validations
    for r in results:
        if r["condition"] != "augmented" or not r.get("augment_metrics"):
            continue
        m = r["augment_metrics"]
        if m["validations_passed"] or m["validations_failed"]:
            for phase in m.get("phases_augmented", []):
                phase_stats[phase]["passed"] += m["validations_passed"]
                phase_stats[phase]["failed"] += m["validations_failed"]

    out = {}
    for phase, stats in sorted(phase_stats.items()):
        total = stats["passed"] + stats["failed"]
        out[phase] = {
            "passed": stats["passed"],
            "failed": stats["failed"],
            "rate": round(stats["passed"] / max(total, 1), 2),
        }
    return out


def export_markdown_table(agg: dict, overhead: dict) -> str:
    """Generate paper-ready markdown table."""
    dims = ["completeness", "correctness", "consistency", "code_quality"]
    dim_labels = {
        "completeness": "Completeness",
        "correctness": "Correctness",
        "consistency": "Consistency",
        "code_quality": "Code Quality",
    }

    lines = [
        "| Metric | Baseline | Augmented | Delta |",
        "|--------|----------|-----------|-------|",
    ]

    for dim in dims:
        b = agg.get("baseline", {}).get(dim, {})
        a = agg.get("augmented", {}).get(dim, {})
        b_str = f"{b.get('mean', 0):.2f} +/- {b.get('std', 0):.2f}"
        a_str = f"{a.get('mean', 0):.2f} +/- {a.get('std', 0):.2f}"
        delta = a.get("mean", 0) - b.get("mean", 0)
        delta_str = f"{delta:+.2f}"
        lines.append(f"| {dim_labels[dim]} | {b_str} | {a_str} | {delta_str} |")

    # Duration row
    b_dur = agg.get("baseline", {}).get("duration_s", {})
    a_dur = agg.get("augmented", {}).get("duration_s", {})
    lines.append(
        f"| Duration (s) | {b_dur.get('mean', 0):.1f} +/- {b_dur.get('std', 0):.1f} "
        f"| {a_dur.get('mean', 0):.1f} +/- {a_dur.get('std', 0):.1f} "
        f"| +{overhead.get('overhead_pct', 0):.1f}% |"
    )

    return "\n".join(lines)


def print_ascii_chart(label: str, baseline: float, augmented: float, width: int = 40) -> None:
    """Print a simple ASCII bar chart comparing two values."""
    max_val = max(baseline, augmented, 0.01)
    b_bar = int(baseline / max_val * width)
    a_bar = int(augmented / max_val * width)

    print(f"\n  {label}")
    print(f"  Baseline:  {'#' * b_bar}{'.' * (width - b_bar)} {baseline:.2f}")
    print(f"  Augmented: {'#' * a_bar}{'.' * (width - a_bar)} {augmented:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze tool-augmentation JSONL logs")
    parser.add_argument("paths", nargs="*", help="JSONL files or directories to analyze")
    parser.add_argument("--compare", action="store_true", help="Compare multiple runs side-by-side")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    # Experiment analysis flags
    parser.add_argument("--experiment", action="store_true", help="Analyze experiment results")
    parser.add_argument("--results-dir", type=str, default="experiments/results",
                        help="Path to experiment results directory")
    parser.add_argument("--markdown", action="store_true", help="Output paper-ready markdown table")
    parser.add_argument("--charts", action="store_true", help="Output ASCII comparison charts")
    args = parser.parse_args()

    # Experiment analysis mode
    if args.experiment:
        results_dir = Path(args.results_dir)
        results = load_experiment_results(results_dir)

        if not results:
            print(f"No experiment results found in {results_dir}", file=sys.stderr)
            sys.exit(1)

        agg = aggregate_by_condition(results)
        overhead = compute_overhead(results)
        phase_qual = per_phase_quality(results)

        if args.json:
            print(json.dumps({
                "aggregated": agg,
                "overhead": overhead,
                "per_phase": phase_qual,
                "n_results": len(results),
            }, indent=2))
        elif args.markdown:
            print(export_markdown_table(agg, overhead))
            if phase_qual:
                print("\n| Phase | Passed | Failed | Rate |")
                print("|-------|--------|--------|------|")
                for phase, stats in phase_qual.items():
                    print(f"| {phase} | {stats['passed']} | {stats['failed']} | {stats['rate']:.0%} |")
        elif args.charts:
            dims = ["completeness", "correctness", "consistency", "code_quality"]
            for dim in dims:
                b = agg.get("baseline", {}).get(dim, {}).get("mean", 0)
                a = agg.get("augmented", {}).get(dim, {}).get("mean", 0)
                print_ascii_chart(dim.replace("_", " ").title(), b, a)
            print_ascii_chart(
                "Duration (s)",
                overhead["baseline_mean_s"],
                overhead["augmented_mean_s"],
            )
        else:
            # Default: print summary
            print(f"Experiment Results: {len(results)} runs loaded")
            for cond in ("baseline", "augmented"):
                c = agg.get(cond, {})
                print(f"\n  {cond.upper()} (n={c.get('n', 0)}):")
                for dim in ["completeness", "correctness", "consistency", "code_quality"]:
                    d = c.get(dim, {})
                    print(f"    {dim}: {d.get('mean', 0):.2f} +/- {d.get('std', 0):.2f}")
                dur = c.get("duration_s", {})
                print(f"    duration: {dur.get('mean', 0):.1f}s +/- {dur.get('std', 0):.1f}s")

            print(f"\n  Overhead: {overhead['delta_s']}s ({overhead['overhead_pct']:+.1f}%)")

            if phase_qual:
                print("\n  Per-phase validation:")
                for phase, stats in phase_qual.items():
                    print(f"    {phase}: {stats['passed']}P/{stats['failed']}F ({stats['rate']:.0%})")

        return

    # Original JSONL analysis mode
    if not args.paths:
        parser.print_help()
        sys.exit(1)

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
