#!/usr/bin/env python3
"""LLM-as-Judge quality evaluator for experiment runs.

Fetches PR diffs from GitHub, sends them to Claude with a judge prompt,
and writes structured quality scores (4 dimensions, 1-5 each).

Usage:
    uv run python quality_evaluator.py                          # evaluate all
    uv run python quality_evaluator.py --project dexter         # filter by project
    uv run python quality_evaluator.py --feature dex-01         # filter by feature
    uv run python quality_evaluator.py --force                  # re-evaluate existing
    uv run python quality_evaluator.py --model opus             # use opus instead of sonnet
    uv run python quality_evaluator.py --json                   # JSON output
    uv run python quality_evaluator.py --dry-run                # show what would be evaluated
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "experiments" / "results"
CLAUDE_BIN = "claude"

# Lock/generated files to strip from diffs
LOCK_FILE_PATTERNS = [
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "Gemfile.lock",
    "go.sum",
]

MAX_DIFF_LINES = 3000

MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}

JUDGE_PROMPT = """\
You are an expert code reviewer evaluating a pull request.

## Feature Description
{description}

## PR Diff ({diff_lines} lines, {changed_files_count} files changed)
Changed files: {changed_files}

```diff
{diff}
```

## Instructions
Score this PR on 4 dimensions (1-5 each):

1. **Completeness** (1-5): Does the PR address all requirements in the feature description?
   - 1: Missing most requirements
   - 3: Addresses core requirements but misses some details
   - 5: Fully addresses all requirements

2. **Correctness** (1-5): Is the implementation technically sound?
   - 1: Major bugs or logic errors
   - 3: Works for happy path but has edge case issues
   - 5: Robust, handles edge cases correctly

3. **Style** (1-5): Does it follow codebase conventions and language idioms?
   - 1: Ignores project conventions entirely
   - 3: Mostly follows conventions with some inconsistencies
   - 5: Perfectly consistent with project style

4. **Quality** (1-5): Is the code clean, well-structured, and maintainable?
   - 1: Messy, hard to follow, no structure
   - 3: Readable but could be improved
   - 5: Clean, well-organized, good abstractions

For each dimension, provide a 1-2 sentence rationale explaining your score.
Be calibrated: 3 is average/acceptable, 5 is exceptional. Most PRs should score 2-4.

IMPORTANT: You MUST respond with ONLY a JSON object, no markdown, no explanation, no code fences.
The JSON must have exactly these keys:
  completeness (integer 1-5), correctness (integer 1-5), style (integer 1-5), quality (integer 1-5),
  rationale_completeness (string), rationale_correctness (string), rationale_style (string), rationale_quality (string)

Example response:
{{"completeness": 3, "correctness": 4, "style": 3, "quality": 4, "rationale_completeness": "Covers main requirements but misses edge cases.", "rationale_correctness": "Logic is sound, handles errors.", "rationale_style": "Mostly follows conventions.", "rationale_quality": "Clean and readable."}}"""

JUDGE_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "completeness": {"type": "integer", "minimum": 1, "maximum": 5},
        "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
        "style": {"type": "integer", "minimum": 1, "maximum": 5},
        "quality": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale_completeness": {"type": "string"},
        "rationale_correctness": {"type": "string"},
        "rationale_style": {"type": "string"},
        "rationale_quality": {"type": "string"},
    },
    "required": [
        "completeness", "correctness", "style", "quality",
        "rationale_completeness", "rationale_correctness",
        "rationale_style", "rationale_quality",
    ],
})


# ---------------------------------------------------------------------------
# PR diff fetching
# ---------------------------------------------------------------------------

def extract_pr_info(stdout_log: str) -> tuple[str | None, int | None]:
    """Extract PR URL and number from stdout.log.

    Returns (pr_url, pr_number) or (None, None) if not found.
    """
    match = re.search(
        r"PR: (https://github\.com/([^/]+/[^/]+)/pull/(\d+))", stdout_log
    )
    if match:
        return match.group(1), int(match.group(3))
    return None, None


def extract_repo(pr_url: str) -> str:
    """Extract owner/repo from a GitHub PR URL."""
    match = re.search(r"github\.com/([^/]+/[^/]+)/pull/", pr_url)
    return match.group(1) if match else ""


def fetch_pr_diff(pr_number: int, repo: str) -> str | None:
    """Fetch PR diff via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--repo", repo],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def filter_diff(diff: str) -> tuple[str, list[str]]:
    """Remove lock files from diff, return (filtered_diff, changed_files)."""
    lines = diff.split("\n")
    filtered = []
    changed_files = []
    skip_file = False
    current_file = None

    for line in lines:
        # Detect file header
        if line.startswith("diff --git"):
            # Extract filename from "diff --git a/foo b/foo"
            parts = line.split(" b/", 1)
            current_file = parts[1] if len(parts) > 1 else None

            skip_file = False
            if current_file:
                basename = current_file.split("/")[-1]
                if basename in LOCK_FILE_PATTERNS:
                    skip_file = True
                else:
                    changed_files.append(current_file)

        if not skip_file:
            filtered.append(line)

    return "\n".join(filtered), changed_files


def truncate_diff(diff: str, max_lines: int = MAX_DIFF_LINES) -> str:
    """Truncate diff to max_lines, adding a note if truncated."""
    lines = diff.split("\n")
    if len(lines) <= max_lines:
        return diff
    return "\n".join(lines[:max_lines]) + f"\n\n[... truncated at {max_lines} lines, {len(lines)} total ...]"


# ---------------------------------------------------------------------------
# Claude judge invocation
# ---------------------------------------------------------------------------

def run_judge(
    description: str,
    diff: str,
    changed_files: list[str],
    diff_lines: int,
    model: str = "sonnet",
) -> dict:
    """Call Claude as judge and return parsed scores."""
    prompt = JUDGE_PROMPT.format(
        description=description,
        diff=diff,
        diff_lines=diff_lines,
        changed_files_count=len(changed_files),
        changed_files=", ".join(changed_files),
    )

    model_id = MODEL_MAP.get(model, model)
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--output-format", "text",
        "--model", model_id,
    ]

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"error": "judge_timeout"}
    except FileNotFoundError:
        return {"error": "claude_not_found"}

    if result.returncode != 0:
        return {"error": f"claude_exit_{result.returncode}", "stderr": result.stderr[:500]}

    return _parse_json_findings(result.stdout.strip())


def _parse_json_findings(text: str) -> dict:
    """Extract JSON from Claude response (belt-and-suspenders)."""
    if not isinstance(text, str):
        try:
            return dict(text)
        except (TypeError, ValueError):
            return {"raw_response": str(text)[:500], "parse_error": True}

    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    return {"raw_response": text[:500], "parse_error": True}


# ---------------------------------------------------------------------------
# Run discovery & evaluation
# ---------------------------------------------------------------------------

def discover_runs(
    project_filter: str | None = None,
    feature_filter: str | None = None,
) -> list[Path]:
    """Find all valid run directories."""
    if not RESULTS_DIR.exists():
        return []

    runs = []
    for d in sorted(RESULTS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("summary"):
            continue
        metadata_path = d / "metadata.json"
        if not metadata_path.exists():
            continue

        metadata = json.loads(metadata_path.read_text())

        if project_filter and metadata.get("project") != project_filter:
            continue
        if feature_filter and metadata.get("feature_id") != feature_filter:
            continue

        runs.append(d)

    return runs


def should_evaluate(run_dir: Path, force: bool) -> bool:
    """Check if a run needs evaluation."""
    quality_path = run_dir / "quality.json"
    if not quality_path.exists():
        return True
    if force:
        return True

    existing = json.loads(quality_path.read_text())
    # Re-evaluate if previous run had an error but not if it has valid scores
    if existing.get("scores") is None:
        return True
    return False


def evaluate_run(run_dir: Path, model: str) -> dict:
    """Evaluate a single run. Returns quality result dict."""
    metadata = json.loads((run_dir / "metadata.json").read_text())
    stdout_path = run_dir / "stdout.log"

    run_id = metadata.get("run_id", run_dir.name)
    feature_id = metadata.get("feature_id", "")
    project = metadata.get("project", "")
    condition = metadata.get("condition", "")
    description = metadata.get("description", "")

    base_result = {
        "run_id": run_id,
        "feature_id": feature_id,
        "project": project,
        "condition": condition,
        "evaluator_model": model,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Extract PR info
    if not stdout_path.exists():
        return {**base_result, "scores": None, "error": "no_stdout_log"}

    stdout_text = stdout_path.read_text()
    pr_url, pr_number = extract_pr_info(stdout_text)

    if not pr_url or not pr_number:
        return {**base_result, "scores": None, "error": "no_pr_found"}

    repo = extract_repo(pr_url)
    base_result.update({
        "pr_number": pr_number,
        "pr_repo": repo,
        "pr_url": pr_url,
    })

    # Fetch and filter diff
    raw_diff = fetch_pr_diff(pr_number, repo)
    if not raw_diff:
        return {**base_result, "scores": None, "error": "diff_fetch_failed"}

    filtered_diff, changed_files = filter_diff(raw_diff)
    diff_lines = len(filtered_diff.split("\n"))
    display_diff = truncate_diff(filtered_diff)

    base_result.update({
        "changed_files": changed_files,
        "diff_lines": diff_lines,
    })

    # Call judge
    judge_result = run_judge(
        description=description,
        diff=display_diff,
        changed_files=changed_files,
        diff_lines=diff_lines,
        model=model,
    )

    if "error" in judge_result:
        return {**base_result, "scores": None, "error": judge_result["error"]}

    if "parse_error" in judge_result:
        return {
            **base_result,
            "scores": None,
            "error": "parse_failed",
            "raw_response": judge_result.get("raw_response", ""),
        }

    # Build structured output
    scores = {
        "completeness": judge_result.get("completeness", 0),
        "correctness": judge_result.get("correctness", 0),
        "style": judge_result.get("style", 0),
        "quality": judge_result.get("quality", 0),
    }
    composite = sum(scores.values()) / len(scores)

    rationale = {
        "completeness": judge_result.get("rationale_completeness", ""),
        "correctness": judge_result.get("rationale_correctness", ""),
        "style": judge_result.get("rationale_style", ""),
        "quality": judge_result.get("rationale_quality", ""),
    }

    return {
        **base_result,
        "scores": scores,
        "composite_score": round(composite, 2),
        "rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Summary & comparison tables
# ---------------------------------------------------------------------------

def print_summary(results: list[dict]) -> None:
    """Print comparison summary table."""
    # Separate into evaluated vs error
    evaluated = [r for r in results if r.get("scores")]
    errors = [r for r in results if not r.get("scores")]

    if not evaluated and not errors:
        print("No runs to report.")
        return

    # Per-feature comparison
    features: dict[str, dict[str, dict]] = {}
    for r in evaluated:
        key = r["feature_id"]
        if key not in features:
            features[key] = {"project": r["project"]}
        features[key][r["condition"]] = r

    if features:
        print("\n## Per-Feature Comparison\n")
        print(f"{'Feature':<10}| {'Project':<16}| {'Baseline':<20}| {'Augmented':<20}| {'Delta':<6}")
        print("-" * 10 + "+" + "-" * 16 + "+" + "-" * 20 + "+" + "-" * 20 + "+" + "-" * 6)

        for fid in sorted(features.keys()):
            fdata = features[fid]
            project = fdata["project"]

            b = fdata.get("baseline", {})
            a = fdata.get("augmented", {})

            b_scores = b.get("scores", {})
            a_scores = a.get("scores", {})

            if b_scores:
                b_str = f"C={b_scores['completeness']} R={b_scores['correctness']} S={b_scores['style']} Q={b_scores['quality']}"
                b_comp = b.get("composite_score", 0)
            else:
                b_str = "---"
                b_comp = 0

            if a_scores:
                a_str = f"C={a_scores['completeness']} R={a_scores['correctness']} S={a_scores['style']} Q={a_scores['quality']}"
                a_comp = a.get("composite_score", 0)
            else:
                a_str = "---"
                a_comp = 0

            if b_comp and a_comp:
                delta = f"{a_comp - b_comp:+.2f}"
            else:
                delta = "n/a"

            print(f"{fid:<10}| {project:<16}| {b_str:<20}| {a_str:<20}| {delta:<6}")

    # Overall averages
    by_condition: dict[str, list[dict]] = {"baseline": [], "augmented": []}
    for r in evaluated:
        cond = r.get("condition", "")
        if cond in by_condition:
            by_condition[cond].append(r)

    print(f"\n## Overall\n")
    print(f"{'Condition':<12}| {'Comp':>5} | {'Corr':>5} | {'Style':>5} | {'Qual':>5} | {'Composite':>9} | {'N':>3}")
    print("-" * 12 + "+" + "-" * 7 + "+" + "-" * 7 + "+" + "-" * 7 + "+" + "-" * 7 + "+" + "-" * 11 + "+" + "-" * 5)

    avgs = {}
    for cond in ["baseline", "augmented"]:
        runs = by_condition[cond]
        n = len(runs)
        if n == 0:
            print(f"{cond:<12}| {'---':>5} | {'---':>5} | {'---':>5} | {'---':>5} | {'---':>9} | {0:>3}")
            continue

        avg_comp = sum(r["scores"]["completeness"] for r in runs) / n
        avg_corr = sum(r["scores"]["correctness"] for r in runs) / n
        avg_style = sum(r["scores"]["style"] for r in runs) / n
        avg_qual = sum(r["scores"]["quality"] for r in runs) / n
        avg_composite = sum(r["composite_score"] for r in runs) / n

        avgs[cond] = {
            "completeness": avg_comp,
            "correctness": avg_corr,
            "style": avg_style,
            "quality": avg_qual,
            "composite": avg_composite,
        }

        print(
            f"{cond:<12}| {avg_comp:5.2f} | {avg_corr:5.2f} | {avg_style:5.2f} | {avg_qual:5.2f} | {avg_composite:9.2f} | {n:>3}"
        )

    # Delta row
    if "baseline" in avgs and "augmented" in avgs:
        b, a = avgs["baseline"], avgs["augmented"]
        print(
            f"{'delta':<12}| {a['completeness'] - b['completeness']:+5.2f} | "
            f"{a['correctness'] - b['correctness']:+5.2f} | "
            f"{a['style'] - b['style']:+5.2f} | "
            f"{a['quality'] - b['quality']:+5.2f} | "
            f"{a['composite'] - b['composite']:+9.2f} |"
        )

    # Errors
    if errors:
        print(f"\n## Errors ({len(errors)} runs)\n")
        for r in errors:
            print(f"  {r['run_id']}: {r.get('error', 'unknown')}")


def collect_all_results(runs: list[Path]) -> list[dict]:
    """Load quality.json from all run dirs."""
    results = []
    for run_dir in runs:
        quality_path = run_dir / "quality.json"
        if quality_path.exists():
            results.append(json.loads(quality_path.read_text()))
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM-as-Judge quality evaluator for experiment runs"
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Filter to a specific project (e.g. dexter)",
    )
    parser.add_argument(
        "--feature", type=str, default=None,
        help="Filter to a specific feature ID (e.g. dex-01)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-evaluate runs that already have scores",
    )
    parser.add_argument(
        "--model", type=str, default="sonnet",
        choices=["sonnet", "opus", "haiku"],
        help="Model to use for judging (default: sonnet)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be evaluated without running",
    )
    args = parser.parse_args()

    runs = discover_runs(
        project_filter=args.project,
        feature_filter=args.feature,
    )

    if not runs:
        print("No runs found matching filters.", file=sys.stderr)
        sys.exit(1)

    to_evaluate = [r for r in runs if should_evaluate(r, args.force)]
    already_done = len(runs) - len(to_evaluate)

    print(f"Found {len(runs)} runs ({already_done} already evaluated, {len(to_evaluate)} to evaluate)")

    if args.dry_run:
        print("\n[DRY RUN] Would evaluate:\n")
        for run_dir in to_evaluate:
            meta = json.loads((run_dir / "metadata.json").read_text())
            stdout_path = run_dir / "stdout.log"
            pr_url = "no stdout"
            if stdout_path.exists():
                url, _ = extract_pr_info(stdout_path.read_text())
                pr_url = url or "no PR found"
            print(f"  {run_dir.name}")
            print(f"    {meta.get('project')}/{meta.get('feature_id')} ({meta.get('condition')}) -> {pr_url}")
        # Also print summary of already-evaluated runs
        if already_done > 0:
            print(f"\nAlready evaluated ({already_done}):")
            done_runs = [r for r in runs if r not in to_evaluate]
            results = collect_all_results(done_runs)
            if not args.json:
                print_summary(results)
            else:
                print(json.dumps(results, indent=2))
        return

    # Evaluate
    all_results = []

    # Load existing results for runs we're skipping
    for run_dir in runs:
        if run_dir not in to_evaluate:
            quality_path = run_dir / "quality.json"
            if quality_path.exists():
                all_results.append(json.loads(quality_path.read_text()))

    # Evaluate new/force runs
    for i, run_dir in enumerate(to_evaluate, 1):
        meta = json.loads((run_dir / "metadata.json").read_text())
        label = f"[{i}/{len(to_evaluate)}] {meta.get('feature_id')} ({meta.get('condition')})"
        print(f"{label} evaluating...", end=" ", flush=True)

        start = time.monotonic()
        result = evaluate_run(run_dir, model=args.model)
        elapsed = time.monotonic() - start

        # Write quality.json
        quality_path = run_dir / "quality.json"
        quality_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        all_results.append(result)

        if result.get("scores"):
            scores = result["scores"]
            print(
                f"C={scores['completeness']} R={scores['correctness']} "
                f"S={scores['style']} Q={scores['quality']} "
                f"({result['composite_score']}) [{elapsed:.1f}s]"
            )
        else:
            print(f"error: {result.get('error', 'unknown')} [{elapsed:.1f}s]")

    # Output
    if args.json:
        print(json.dumps(all_results, indent=2))
    else:
        print_summary(all_results)


if __name__ == "__main__":
    main()
