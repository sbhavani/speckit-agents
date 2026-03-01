#!/usr/bin/env python3
"""
Blind Human Preference Study CLI Tool

Runs a blind pairwise comparison study between Full and Full-Augmented conditions.
For each task pair, evaluators see anonymized PR info and choose their preference.

Evaluators should review the PRs in a browser for the full diff.
"""

import argparse
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Configuration
EXPERIMENTS_DIR = Path("/Volumes/SSD-PGU3/code/speckit-agents-experiments/results")


@dataclass
class RunResult:
    run_id: str
    feature_id: str
    project: str
    condition: str
    pr_url: str
    pr_number: int
    repo: str
    changed_files: list[str] = None
    scores: Optional[dict] = None


def load_run_results() -> dict[str, list[RunResult]]:
    """Load all run results from the experiments directory."""
    results: dict[str, list[RunResult]] = {}

    for run_dir in EXPERIMENTS_DIR.iterdir():
        if not run_dir.is_dir():
            continue

        run_name = run_dir.name

        # Skip baseline and augmented-only runs
        if "baseline" in run_name or "_augmented_" not in run_name and "_full" not in run_name:
            continue
        if "_augmented_" in run_name and "full" not in run_name:
            continue

        quality_file = run_dir / "quality.json"
        if not quality_file.exists():
            continue

        try:
            with open(quality_file) as f:
                data = json.load(f)

            # Check if run was successful (has PR)
            if not data.get("pr_number"):
                continue

            condition = data.get("condition", "")
            if condition not in ("full", "full-augmented"):
                continue

            run = RunResult(
                run_id=data["run_id"],
                feature_id=data["feature_id"],
                project=data["project"],
                condition=condition,
                pr_url=data.get("pr_url", ""),
                pr_number=data.get("pr_number", 0),
                repo=data.get("pr_repo", ""),
                changed_files=data.get("changed_files", []),
                scores=data.get("scores"),
            )

            # Group by feature_id
            key = f"{run.project}-{run.feature_id}"
            if key not in results:
                results[key] = []
            results[key].append(run)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not parse {run_dir.name}/quality.json: {e}", file=sys.stderr)
            continue

    return results


def find_successful_pairs(results: dict[str, list[RunResult]]) -> list[tuple[RunResult, RunResult]]:
    """Find feature pairs where both full and full-augmented succeeded."""
    pairs = []

    for feature_id, runs in results.items():
        full_runs = [r for r in runs if r.condition == "full"]
        full_aug_runs = [r for r in runs if r.condition == "full-augmented"]

        if full_runs and full_aug_runs:
            # Take the most recent run for each condition
            full = max(full_runs, key=lambda r: r.run_id)
            aug = max(full_aug_runs, key=lambda r: r.run_id)
            pairs.append((full, aug))

    return pairs


def get_pr_info(pr_repo: str, pr_number: int) -> dict:
    """Fetch PR info from GitHub using gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", pr_repo,
             "--json", "title,body,files,additions,deletions,changedFiles"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            print(f"Warning: Failed to fetch PR #{pr_number} from {pr_repo}: {result.stderr}", file=sys.stderr)
            return {}
    except subprocess.TimeoutExpired:
        print(f"Warning: Timeout fetching PR #{pr_number} from {pr_repo}", file=sys.stderr)
        return {}
    except FileNotFoundError:
        print("Error: gh CLI not found. Please install GitHub CLI.", file=sys.stderr)
        sys.exit(1)


def display_pr_summary(pr_info: dict, version_label: str, pr_url: str):
    """Display PR summary to evaluator."""
    print(f"\n{'='*70}")
    print(f"VERSION {version_label}")
    print(f"{'='*70}")

    title = pr_info.get("title", "No title")
    body = pr_info.get("body", "")
    files = pr_info.get("changedFiles", 0)
    additions = pr_info.get("additions", 0)
    deletions = pr_info.get("deletions", 0)

    print(f"\nTitle: {title}")
    print(f"Files changed: {files} | +{additions} -{deletions}")
    print(f"URL: {pr_url}")

    # Show changed files
    file_list = pr_info.get("files", [])
    if file_list:
        print(f"\nChanged files ({len(file_list)}):")
        for f in file_list[:15]:  # Show first 15 files
            path = f.get("path", "")
            add = f.get("additions", 0)
            del_ = f.get("deletions", 0)
            print(f"  {path}: +{add} -{del_}")
        if len(file_list) > 15:
            print(f"  ... and {len(file_list) - 15} more files")

    # Show description snippet
    if body:
        print(f"\nDescription (first 500 chars):")
        desc = body[:500]
        if len(body) > 500:
            desc += "..."
        print(desc)

    print(f"\n{'='*70}")
    print(f"END OF VERSION {version_label}")
    print(f"{'='*70}\n")


def get_evaluator_choice() -> str:
    """Get evaluator's choice with input validation."""
    while True:
        print("\nWhich version do you prefer?")
        print("  [A] Version A")
        print("  [B] Version B")
        print("  [T] Tie (both equally good/bad)")
        print("  [Q] Quit the study")
        choice = input("\nEnter your choice: ").strip().upper()

        if choice in ("A", "B", "T", "Q"):
            return choice
        print("Invalid choice. Please enter A, B, T, or Q.")


def run_evaluation_session(
    pairs: list[tuple[RunResult, RunResult]],
    num_evaluators: int = 10,
    output_file: Optional[Path] = None
) -> list[dict]:
    """Run the evaluation session with human evaluators."""
    judgments = []
    session_id = random.randint(1000, 9999)

    print(f"\n{'#'*60}")
    print("# BLIND HUMAN PREFERENCE STUDY")
    print(f"# Session ID: {session_id}")
    print(f"# Total tasks: {len(pairs)}")
    print(f"# Evaluators per task: {num_evaluators}")
    print(f"#")
    print(f"# IMPORTANT: Review the full PR diffs in your browser!")
    print(f"# This tool shows summaries but you should click the URLs")
    print(f"# to see the complete code changes.")
    print(f"{'#'*60}\n")

    for task_idx, (full_run, aug_run) in enumerate(pairs, 1):
        print(f"\n{'='*70}")
        print(f"TASK {task_idx}/{len(pairs)}: {full_run.feature_id} ({full_run.project})")
        print(f"{'='*70}")
        print(f"Feature: {full_run.feature_id}")
        print(f"Project: {full_run.project}")

        # Fetch PR info
        print("\nFetching PR info from GitHub...")
        full_pr_info = get_pr_info(full_run.repo, full_run.pr_number)
        aug_pr_info = get_pr_info(aug_run.repo, aug_run.pr_number)

        if not full_pr_info or not aug_pr_info:
            print(f"Warning: Could not fetch one or both PRs. Skipping this task.")
            continue

        # Randomize order for this task
        if random.random() < 0.5:
            first_run, second_run = full_run, aug_run
            first_pr_info, second_pr_info = full_pr_info, aug_pr_info
        else:
            first_run, second_run = aug_run, full_run
            first_pr_info, second_pr_info = aug_pr_info, full_pr_info

        # Store the mapping (blinded)
        version_a = first_run.condition
        version_b = second_run.condition

        print(f"\nLoaded PRs:")
        print(f"  - Version A: {first_run.condition} (PR #{first_run.pr_number})")
        print(f"  - Version B: {second_run.condition} (PR #{second_run.pr_number})")

        # Run evaluations for this task
        for eval_num in range(1, num_evaluators + 1):
            print(f"\n{'*'*70}")
            print(f"*** Evaluator {eval_num}/{num_evaluators} for Task {task_idx} ***")
            print(f"{'*'*70}")

            # Shuffle display order for each evaluator
            if random.random() < 0.5:
                display_pr_summary(first_pr_info, "A", first_run.pr_url)
                display_pr_summary(second_pr_info, "B", second_run.pr_url)
            else:
                display_pr_summary(second_pr_info, "B", second_run.pr_url)
                display_pr_summary(first_pr_info, "A", first_run.pr_url)

            print("\n>>> Please review the full PRs at the URLs above before deciding <<<")
            choice = get_evaluator_choice()

            if choice == "Q":
                print("\nQuitting study...")
                if output_file:
                    save_results(judgments, output_file)
                sys.exit(0)

            # Record judgment
            judgment = {
                "session_id": session_id,
                "task_index": task_idx,
                "task_id": full_run.feature_id,
                "project": full_run.project,
                "evaluator": eval_num,
                "version_a_actual": version_a,
                "version_b_actual": version_b,
                "choice": choice,
                "full_pr_url": full_run.pr_url,
                "aug_pr_url": aug_run.pr_url,
            }
            judgments.append(judgment)

            result_text = {
                "A": "Version A",
                "B": "Version B",
                "T": "Tie"
            }.get(choice, choice)
            print(f"\n>>> Recorded: {result_text} <<<")

    return judgments


def save_results(judgments: list[dict], output_file: Path):
    """Save judgments to output file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(judgments, f, indent=2)
    print(f"\nResults saved to: {output_file}")


def analyze_results(judgments: list[dict]):
    """Print summary analysis of results."""
    if not judgments:
        print("No judgments to analyze.")
        return

    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")

    # Group by task
    by_task: dict[str, dict] = {}
    for j in judgments:
        task_id = j["task_id"]
        if task_id not in by_task:
            by_task[task_id] = {"A": 0, "B": 0, "T": 0}
        by_task[task_id][j["choice"]] += 1

    print(f"\nPer-task results:")
    for task_id, counts in sorted(by_task.items()):
        total = sum(counts.values())
        print(f"  {task_id}: A={counts['A']}, B={counts['B']}, Tie={counts['T']} (n={total})")

    # Overall
    total_a = sum(c["A"] for c in by_task.values())
    total_b = sum(c["B"] for c in by_task.values())
    total_t = sum(c["T"] for c in by_task.values())
    grand_total = total_a + total_b + total_t

    print(f"\nOverall ({grand_total} judgments):")
    print(f"  Full:       {total_a} ({100*total_a/grand_total:.1f}%)")
    print(f"  Full-Aug:  {total_b} ({100*total_b/grand_total:.1f}%)")
    print(f"  Tie:        {total_t} ({100*total_t/grand_total:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Run blind human preference study between Full and Full-Augmented conditions"
    )
    parser.add_argument(
        "--experiments-dir",
        type=Path,
        default=None,
        help="Path to experiments results directory"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("human_preference_study_results.json"),
        help="Output file for judgments"
    )
    parser.add_argument(
        "--num-evaluators",
        type=int,
        default=10,
        help="Number of evaluators per task (default: 10)"
    )
    parser.add_argument(
        "--tasks-per-repo",
        type=int,
        default=2,
        help="Number of tasks to sample per repository (default: 2)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show available tasks without running evaluation"
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Resume from existing results file"
    )

    args = parser.parse_args()

    global EXPERIMENTS_DIR
    if args.experiments_dir:
        EXPERIMENTS_DIR = args.experiments_dir

    if not EXPERIMENTS_DIR.exists():
        print(f"Error: Experiments directory not found: {EXPERIMENTS_DIR}", file=sys.stderr)
        sys.exit(1)

    # Resume from existing file
    existing_judgments = []
    if args.resume and args.resume.exists():
        with open(args.resume) as f:
            existing_judgments = json.load(f)
        print(f"Resumed with {len(existing_judgments)} existing judgments")

    # Load and analyze results
    print("Loading experiment results...")
    results = load_run_results()
    print(f"Found {len(results)} features with full/full-augmented runs")

    pairs = find_successful_pairs(results)
    print(f"Found {len(pairs)} tasks with both conditions successful")

    if not pairs:
        print("Error: No successful task pairs found.", file=sys.stderr)
        sys.exit(1)

    # Group by project
    by_project: dict[str, list[tuple[RunResult, RunResult]]] = {}
    for full, aug in pairs:
        proj = full.project
        if proj not in by_project:
            by_project[proj] = []
        by_project[proj].append((full, aug))

    print("\nTasks by project:")
    for proj, proj_pairs in sorted(by_project.items()):
        print(f"  {proj}: {len(proj_pairs)} tasks")

    # Sample tasks
    sampled_pairs = []
    for proj in sorted(by_project.keys()):
        proj_pairs = by_project[proj]
        # Sample up to args.tasks_per_repo
        selected = random.sample(proj_pairs, min(args.tasks_per_repo, len(proj_pairs)))
        sampled_pairs.extend(selected)

    print(f"\nSampled {len(sampled_pairs)} tasks for evaluation")

    if args.dry_run:
        print("\nDry run - tasks that would be evaluated:")
        for i, (full, aug) in enumerate(sampled_pairs, 1):
            print(f"  {i}. {full.feature_id} ({full.project})")
            print(f"     Full:       {full.pr_url}")
            print(f"     Full-Aug:  {aug.pr_url}")
        return

    # Run evaluation
    judgments = run_evaluation_session(
        sampled_pairs,
        num_evaluators=args.num_evaluators,
        output_file=args.output
    )

    # Add existing judgments if resuming
    if existing_judgments:
        judgments.extend(existing_judgments)

    # Save and analyze
    save_results(judgments, args.output)
    analyze_results(judgments)

    print("\nStudy complete!")


if __name__ == "__main__":
    main()
